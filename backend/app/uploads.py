"""SQLite 文件上传：落盘、配额、清理。

为什么需要这一层：SQLite 是**服务器上的一个文件**，普通用户没法把文件放到服务器上，
所以「上传」是这类产品能不能给陌生人用的分水岭。

三条约束（都可配，见 config.py）：
- 单文件上限：``upload_max_mb_per_file``
- 每个工作空间累计上限：``upload_max_mb_per_workspace``
- 全站累计上限：``upload_max_mb_total``（防止开放注册被塞满磁盘）

并发上传可能让配额被短暂突破几 MB——这个量级不值得为它加锁。
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import settings

ALLOWED_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
# SQLite 文件头，用来挡住"改个后缀就传上来"的垃圾文件
SQLITE_MAGIC = b"SQLite format 3\x00"
_CHUNK = 1024 * 1024


class UploadError(Exception):
    """上传被拒绝（提示可以直接给用户看）。"""


def upload_root() -> Path:
    return settings.data_dir / "uploads"


def workspace_dir(workspace_id: int) -> Path:
    return upload_root() / str(int(workspace_id))


def _dir_mb(path: Path) -> float:
    if not path.is_dir():
        return 0.0
    total = sum(item.stat().st_size for item in path.iterdir() if item.is_file())
    return total / (1024 * 1024)


def workspace_usage_mb(workspace_id: int) -> float:
    return _dir_mb(workspace_dir(workspace_id))


def total_usage_mb() -> float:
    return _dir_mb(upload_root())


def is_managed_path(database: str | None) -> bool:
    """只有我们自己放的文件才允许删。

    用户手填的服务器路径（比如别人的生产库）绝不能因为删数据源就跟着删掉。
    """
    if not database:
        return False
    try:
        target = Path(database).resolve()
        root = upload_root().resolve()
    except (OSError, RuntimeError):
        return False
    return root == target.parent or root in target.parents


async def save_sqlite(file: UploadFile, workspace_id: int) -> Path:
    """把上传的文件落到 ``uploads/{workspace_id}/``，返回最终路径。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise UploadError("只支持 .db / .sqlite / .sqlite3 文件")

    per_file = settings.upload_max_mb_per_file
    cap_ws = settings.upload_max_mb_per_workspace
    cap_total = settings.upload_max_mb_total

    used_ws = workspace_usage_mb(workspace_id)
    used_total = total_usage_mb()
    if used_ws + per_file > cap_ws and used_ws >= cap_ws:
        raise UploadError(f"这个工作空间的上传空间已满（上限 {cap_ws} MB）")
    if used_total >= cap_total:
        raise UploadError("服务器上传空间已满，请联系管理员清理")

    target_dir = workspace_dir(workspace_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4().hex}{suffix}"
    tmp = target.with_suffix(target.suffix + ".part")

    written = 0
    limit = min(per_file, cap_ws - used_ws, cap_total - used_total) * 1024 * 1024
    try:
        with tmp.open("wb") as handle:
            first = True
            while chunk := await file.read(_CHUNK):
                if first:
                    if not chunk.startswith(SQLITE_MAGIC):
                        raise UploadError("这不是一个 SQLite 数据库文件")
                    first = False
                written += len(chunk)
                if written > limit:
                    raise UploadError(
                        f"文件超过上限（单文件 {per_file} MB，"
                        f"本空间剩余 {max(cap_ws - used_ws, 0):.0f} MB）"
                    )
                handle.write(chunk)
        if written == 0:
            raise UploadError("文件是空的")
        tmp.replace(target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    return target


def remove_upload(database: str | None) -> bool:
    """删除一个由我们管理的上传文件；返回是否真的删了。"""
    if not is_managed_path(database):
        return False
    try:
        Path(database).unlink(missing_ok=True)  # type: ignore[arg-type]
        return True
    except OSError:
        return False


def clear_workspace(workspace_id: int) -> None:
    """整目录清掉（运维用，接口层不会调用）。"""
    shutil.rmtree(workspace_dir(workspace_id), ignore_errors=True)