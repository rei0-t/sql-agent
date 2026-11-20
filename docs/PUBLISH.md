# 把项目发到 GitHub（首次）

> 面向没推送过仓库的人。全程 6 分钟，其中 2 分钟是等待。

## 1. 在 GitHub 上建一个空仓库

1. 打开 https://github.com/new
2. **Repository name** 填 `sql-agent`
3. 选 **Public**（开源）
4. **不要**勾选 "Add a README file"、".gitignore"、"license" —— 三项都留空
5. 点 **Create repository**

建完页面会显示一堆命令，**不用管**，按下面来。

## 2. 在 Windows 上执行 5 条命令

打开 PowerShell（开始菜单搜 PowerShell），逐段粘贴：

```powershell
cd E:\deepseekHarness\sql-agent

git config user.name "你的名字"
git config user.email "你的邮箱"

git commit -m "feat: 只读 NL2SQL 控制台（BYOK + 开发者 API）"
```

```powershell
git remote add origin https://github.com/你的GitHub用户名/sql-agent.git
git push -u origin main
```

第一次 `push` 会弹出一个浏览器窗口让你登录 GitHub（这是 Git Credential Manager 在要授权），
点 **Sign in with your browser** → 登录 → **Authorize**。之后就不用再登了。

看到这样的输出就成功了：

```
 * [new branch]      main -> main
branch 'main' set up to track 'origin/main'.
```

刷新 GitHub 页面，能看到 README 和代码。

## 3. 以后每次改完代码

```powershell
cd E:\deepseekHarness\sql-agent
git add -A
git commit -m "改了什么"
git push
```

## 4. 顺手打开 CI

仓库页面 → **Actions** 标签 → 如果提示是否启用 workflow，点 **I understand my workflows, go ahead and enable them**。
之后每次 push 会自动跑后端测试和前端构建，README 顶上的徽章会变绿。

---

## 常见报错

| 报错 | 原因 | 解决 |
|---|---|---|
| `remote origin already exists` | 之前加过 | `git remote set-url origin https://github.com/你的用户名/sql-agent.git` |
| `Updates were rejected` | 远端有你本地没有的提交（通常是建仓库时勾了 README） | `git pull --rebase origin main` 再 `git push` |
| `Authentication failed` | 凭据过期 | Windows 搜索「凭据管理器」→ 删掉 github.com 的条目 → 重新 push |
| `src refspec main does not match any` | 还没提交 | 确认 `git commit` 那步成功了：`git log --oneline -1` |
| `Permission denied (publickey)` | 用的是 SSH 地址但没配密钥 | 把 remote 换成 https 地址（上面给的格式） |

## 别忘了

- 仓库里**不能有** `.env`、`.env.prod`、数据库文件 —— `.gitignore` 已经挡住了，但提交前扫一眼
- 这个项目用的是 Apache-2.0，`LICENSE` 已放好，不用改
- 建议在仓库 About 里填一句话描述 + 加上 topics：`text-to-sql` `nl2sql` `llm` `sqlite` `mysql` `postgresql` `vue` `fastapi`