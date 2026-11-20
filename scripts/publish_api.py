"""用 GitHub REST API 发布仓库（github.com 被网络封锁时的替代方案）。

为什么需要它：有些网络（例如校园网）会把 github.com 解析到 127.0.0.1，
导致 `git push` 必然失败；但 api.github.com 通常是通的。
这个脚本只访问 api.github.com，用 Git Data API 一次性建仓库并提交整棵树。

用法：
    python scripts/publish_api.py --token <你的 PAT> --repo sql-agent
    python scripts/publish_api.py --token <你的 PAT> --repo sql-agent --dry-run
    python scripts/publish_api.py --token <你的 PAT> --repo sql-agent --private

Token 权限（Fine-grained，最小集）：
    Administration: Read and write   （创建仓库）
    Contents:       Read and write   （写文件、建提交）
有效期设 1 天即可，发布完立刻删除。

注意：
    - 只提交 `git ls-files` 里的文件（也就是你已经 add 的），不会误传 node_modules / .venv
    - 额外兜底：.env / .env.prod / *.db 一律跳过
    - 若仓库已有提交，会以当前 HEAD 为父提交合并，不会删掉已有文件
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

import httpx

# 有些网络（校园网、企业网）会在中间做 TLS 拦截：证书装在 Windows 证书库，
# Python 自带的 certifi 不认，会报 CERTIFICATE_VERIFY_FAILED。
# truststore 让 Python 直接走系统证书库；没装就退回默认行为。
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

API = "https://api.github.com"
ROOT = Path(__file__).resolve().parent.parent
SKIP_SUFFIXES = (".env", ".env.prod", ".db", ".sqlite3")
BLOB_CONCURRENCY = 6


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败：{result.stderr.strip()}")
    return result.stdout


def tracked_files() -> list[Path]:
    raw = git("ls-files", "-z")
    paths: list[Path] = []
    for item in raw.split("\0"):
        if not item:
            continue
        path = ROOT / item
        if path.name in (".env", ".env.prod") or path.suffix in (".db", ".sqlite3"):
            print(f"  跳过敏感文件：{item}")
            continue
        if path.is_file():
            paths.append(path)
    return sorted(paths)


def mode_for(path: Path) -> str:
    return "100755" if path.suffix in (".sh",) else "100644"


class Publisher:
    def __init__(self, token: str) -> None:
        self.token = token
        self.client = httpx.Client(
            base_url=API,
            timeout=60,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "sql-agent-publisher",
            },
        )

    def request(self, method: str, url: str, **kwargs):
        response = self.client.request(method, url, **kwargs)
        if response.status_code == 401:
            raise SystemExit("Token 无效（401）。请确认没有过期、没有复制漏字符。")
        if response.status_code == 403:
            raise SystemExit(
                f"权限不足或被限流（403）：{response.text[:300]}\n"
                "检查 token 是否勾了 Administration / Contents 的 write 权限。"
            )
        return response

    def whoami(self) -> dict:
        return self.request("GET", "/user").json()

    def ensure_repo(self, owner: str, repo: str, private: bool) -> dict:
        existing = self.client.get(f"/repos/{owner}/{repo}")
        if existing.status_code == 200:
            print(f"仓库已存在：{owner}/{repo}")
            return existing.json()
        if existing.status_code != 404:
            raise SystemExit(f"查询仓库失败：{existing.status_code} {existing.text[:200]}")

        print(f"创建仓库 {owner}/{repo} …")
        created = self.request(
            "POST",
            "/user/repos",
            json={
                "name": repo,
                "description": "自然语言查数据库：生成 SQL 并在只读连接上执行（BYOK，含开发者 API）",
                "private": private,
                "has_issues": True,
                "has_wiki": False,
                "auto_init": False,
            },
        )
        if created.status_code not in (200, 201):
            raise SystemExit(f"创建失败：{created.status_code} {created.text[:300]}")
        return created.json()

    def head(self, owner: str, repo: str) -> tuple[str | None, str | None]:
        ref = self.client.get(f"/repos/{owner}/{repo}/git/ref/heads/main")
        if ref.status_code != 200:
            return None, None
        parent = ref.json()["object"]["sha"]
        commit = self.client.get(f"/repos/{owner}/{repo}/git/commits/{parent}")
        base_tree = commit.json()["tree"]["sha"] if commit.status_code == 200 else None
        return parent, base_tree

    def seed_empty(self, owner: str, repo: str) -> tuple[str, str]:
        """空仓库不能建 blob（409），先用 Contents API 种一个提交把仓库激活。

        最后会用force 把分支指向一个无父提交，所以这个种子提交不会留在历史里。
        """
        print("仓库为空，先创建初始提交 …")
        response = self.request(
            "PUT",
            f"/repos/{owner}/{repo}/contents/README.md",
            json={
                "message": "chore: bootstrap",
                "content": base64.b64encode(b"# sql-agent\n").decode("ascii"),
            },
        )
        if response.status_code not in (200, 201):
            raise SystemExit(f"初始化失败：{response.status_code} {response.text[:300]}")
        parent, base_tree = self.head(owner, repo)
        if not parent or not base_tree:
            raise SystemExit("初始化后仍读不到 HEAD，稍等几秒重跑即可")
        return parent, base_tree

    def upload_blobs(self, owner: str, repo: str, paths: list[Path]) -> dict[str, str]:
        """并发建 blob，返回 path -> sha。"""
        import concurrent.futures

        def make_blob(path: Path) -> tuple[str, str]:
            content = base64.b64encode(path.read_bytes()).decode("ascii")
            response = self.request(
                "POST", f"/repos/{owner}/{repo}/git/blobs", json={"content": content, "encoding": "base64"}
            )
            if response.status_code not in (200, 201):
                raise SystemExit(f"上传 {path.name} 失败：{response.status_code} {response.text[:200]}")
            return str(path.relative_to(ROOT)).replace("\\", "/"), response.json()["sha"]

        result: dict[str, str] = {}
        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=BLOB_CONCURRENCY) as pool:
            futures = {pool.submit(make_blob, p): p for p in paths}
            for future in concurrent.futures.as_completed(futures):
                rel, sha = future.result()
                result[rel] = sha
                done += 1
                if done % 20 == 0 or done == len(paths):
                    print(f"  已上传 {done}/{len(paths)}")
        return result

    def publish(self, repo: str, message: str, private: bool, squash: bool = False) -> dict:
        user = self.whoami()
        owner = user["login"]
        print(f"身份：{owner}")

        info = self.ensure_repo(owner, repo, private)
        parent, base_tree = self.head(owner, repo)

        seeded = False
        if parent is None:
            parent, base_tree = self.seed_empty(owner, repo)
            seeded = True

        paths = tracked_files()
        total_kb = sum(p.stat().st_size for p in paths) / 1024
        print(f"待上传 {len(paths)} 个文件，共 {total_kb:.0f} KB（父提交：{parent or '无，首次提交'}）")

        blobs = self.upload_blobs(owner, repo, paths)
        tree_entries = [
            {"path": rel, "mode": mode_for(ROOT / rel), "type": "blob", "sha": sha}
            for rel, sha in blobs.items()
        ]

        tree_payload: dict = {"tree": tree_entries}
        if base_tree:
            tree_payload["base_tree"] = base_tree
        tree = self.request("POST", f"/repos/{owner}/{repo}/git/trees", json=tree_payload)
        if tree.status_code not in (200, 201):
            raise SystemExit(f"建 tree 失败：{tree.status_code} {tree.text[:300]}")

        commit_payload = {
            "message": message,
            "tree": tree.json()["sha"],
            # 种过初始提交 / 显式 squash 时去掉父提交：最终历史只有一个干净的提交
            "parents": [] if (seeded or squash) else ([parent] if parent else []),
        }
        commit = self.request("POST", f"/repos/{owner}/{repo}/git/commits", json=commit_payload)
        if commit.status_code not in (200, 201):
            raise SystemExit(f"建提交失败：{commit.status_code} {commit.text[:300]}")
        commit_sha = commit.json()["sha"]

        if seeded or squash:
            ref = self.request(
                "PATCH",
                f"/repos/{owner}/{repo}/git/refs/heads/main",
                json={"sha": commit_sha, "force": True},
            )
        elif parent:
            ref = self.request(
                "PATCH", f"/repos/{owner}/{repo}/git/refs/heads/main", json={"sha": commit_sha, "force": False}
            )
        else:
            ref = self.request(
                "POST", f"/repos/{owner}/{repo}/git/refs", json={"ref": "refs/heads/main", "sha": commit_sha}
            )
        if ref.status_code not in (200, 201):
            raise SystemExit(f"更新分支失败：{ref.status_code} {ref.text[:300]}")

        if not info.get("default_branch") or info.get("default_branch") != "main":
            self.request("PATCH", f"/repos/{owner}/{repo}", json={"default_branch": "main"})

        return {"owner": owner, "repo": repo, "commit": commit_sha, "files": len(paths)}


def main() -> None:
    parser = argparse.ArgumentParser(description="用 GitHub API 发布仓库")
    parser.add_argument("--token", required=True, help="Fine-grained PAT")
    parser.add_argument("--repo", default="sql-agent")
    parser.add_argument("--message", default="feat: read-only NL2SQL console (BYOK + developer API)")
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--squash", action="store_true", help="覆盖远端历史，保持单提交")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    paths = tracked_files()
    total_kb = sum(p.stat().st_size for p in paths) / 1024
    print(f"[dry-run] {len(paths)} 个文件，{total_kb:.0f} KB")
    for path in paths[:10]:
        print(f"  {path.relative_to(ROOT)}")
    if len(paths) > 10:
        print(f"  …还有 {len(paths) - 10} 个")
    if args.dry_run:
        return

    publisher = Publisher(args.token)
    result = publisher.publish(args.repo, args.message, args.private, squash=args.squash)
    url = f"https://github.com/{result['owner']}/{result['repo']}"
    print(
        json.dumps(
            {
                "repo": url,
                "commit": result["commit"][:12],
                "files": result["files"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\n完成：{url}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)