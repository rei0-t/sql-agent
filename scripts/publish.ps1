# 一条命令把仓库推到 GitHub。
#
#   # 先在 https://github.com/new 建一个空仓库（不要勾 README / .gitignore / license）
#   powershell -ExecutionPolicy Bypass -File scripts/publish.ps1 -RepoUrl https://github.com/你的用户名/sql-agent.git -Name "你的名字" -Email "你的邮箱"
#
# 第一次 push 会弹出浏览器让你授权 GitHub（Git Credential Manager），点一次之后就不用了。

param(
    [string]$RepoUrl = "",
    [string]$Name = "",
    [string]$Email = "",
    [string]$Branch = "main",
    [string]$Message = "feat: read-only NL2SQL console (BYOK + developer API)"
)

$ErrorActionPreference = "Stop"

if (-not $RepoUrl) {
    Write-Host "用法：" -ForegroundColor Yellow
    Write-Host '  powershell -ExecutionPolicy Bypass -File scripts/publish.ps1 -RepoUrl https://github.com/你的用户名/sql-agent.git -Name "你的名字" -Email "你的邮箱"'
    Write-Host ""
    Write-Host "RepoUrl 从 GitHub 建库后的页面上复制（地址以 .git 结尾）。"
    exit 1
}

$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
Write-Host "仓库目录: $root"

if (-not $RepoUrl.StartsWith("https://")) {
    Write-Host "RepoUrl 要用 https:// 开头，例如 https://github.com/you/sql-agent.git" -ForegroundColor Red
    exit 1
}

if ($Name) { git config user.name $Name }
if ($Email) { git config user.email $Email }

$cfgName = git config user.name
$cfgEmail = git config user.email
if (-not $cfgName -or -not $cfgEmail) {
    Write-Host '还没设置提交身份。请加参数：-Name "你的名字" -Email "你的邮箱"' -ForegroundColor Red
    exit 1
}
Write-Host "提交身份: $cfgName <$cfgEmail>"

# 提交前最后一道保险：不能把 .env / .env.prod / 数据库文件带上去
$forbidden = git status --porcelain --untracked-files=all | Select-String -Pattern '\.env\.prod$|(^|\s)\.env$|\.db$'
if ($forbidden) {
    Write-Host "发现不应提交的文件：" -ForegroundColor Red
    $forbidden | ForEach-Object { Write-Host ("  " + $_.Line) -ForegroundColor Red }
    Write-Host "请先清理（检查 .gitignore）再重跑" -ForegroundColor Red
    exit 1
}

git add -A
$pending = git status --porcelain
if ($pending) {
    git commit -m $Message | Out-Host
    Write-Host "已提交 $($pending.Count) 个文件"
} else {
    Write-Host "没有待提交的变更"
}

$remotes = git remote
if ($remotes -contains "origin") {
    git remote set-url origin $RepoUrl
} else {
    git remote add origin $RepoUrl
}
Write-Host "远端: $RepoUrl"

Write-Host ""
Write-Host "开始 push —— 如果弹出浏览器，登录 GitHub 并点授权" -ForegroundColor Yellow
git push -u origin $Branch

Write-Host ""
Write-Host "完成。仓库地址: $($RepoUrl -replace '\.git$','')" -ForegroundColor Green
Write-Host "去 Actions 标签点一下 Enable，CI 就会开始跑。"