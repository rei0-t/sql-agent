# SQL-agent 运维手册（写给不熟悉服务器的人）

> 这份文档回答三类问题：**开源怎么维护**、**怎么部署上线**、**上线之后每天要做什么**。
> 不解释代码原理（那看 [TUTORIAL.md](TUTORIAL.md)），只讲"点哪里、粘什么、看到什么算正常"。

---

## 目录

- [第一部分：先搞清楚你在维护什么](#第一部分先搞清楚你在维护什么)
- [第二部分：开源仓库怎么维护](#第二部分开源仓库怎么维护)
- [第三部分：部署上线（从零到能访问）](#第三部分部署上线从零到能访问)
- [第四部分：日常运维（每天/每周/每月）](#第四部分日常运维每天每周每月)
- [第五部分：出问题怎么办](#第五部分出问题怎么办)
- [第六部分：费用与安全](#第六部分费用与安全)
- [第七部分：小白术语表](#第七部分小白术语表)
- [附录：把项目讲清楚（面试用）](#附录把项目讲清楚面试用)

---

## 第一部分：先搞清楚你在维护什么

### 你的系统长这样

```
用户浏览器
    │  https://你的域名 或 http://47.238.174.161
    ▼
┌─────────────────────────────────────┐
│  Nginx（80/443 端口，反向代理）      │  ← 系统装的，配置在 /etc/nginx/conf.d/
└──────────────┬──────────────────────┘
               │ 转发到 127.0.0.1:8080
               ▼
┌─────────────────────────────────────┐
│  Docker 容器 app                     │  ← Python 后端 + 打包好的前端
│  （/opt/sql-agent 里的代码构建而成）  │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│  Docker 容器 db（PostgreSQL）        │  ← 存账号、数据源、审计、额度
└─────────────────────────────────────┘
```

**三句话记住：**

1. **代码在** `/opt/sql-agent`（git 仓库，`git pull` 更新）
2. **配置在** `/opt/sql-agent/.env.prod`（密码、Key、开关都在这）
3. **数据在** `deploy/aliyun/data`（上传的 SQLite 文件、示例库）+ Docker 卷 `pgdata`（账号与审计）

### 什么能改、什么别碰

| 想做的事 | 改哪里 | 风险 |
|---|---|---|
| 改模型 / 额度 / 开关 | `.env.prod` 然后重启 app | 低 |
| 改管理员密码 | 网页「设置 → 修改密码」 | 低 |
| 改数据源 | 网页「数据源」 | 低 |
| 改 Nginx / 证书 | `/etc/nginx/conf.d/sql-agent.conf` | 中，改完必须 `nginx -t` |
| 改代码 | 本地改 → 推 GitHub → 服务器 `git pull` | 中 |
| 删 `deploy/aliyun/data` | **别删**，上传的库都在里面 |
| 删 Docker 卷 `pgdata` | **绝对别删**，删了账号和数据源全没 |

---

## 第二部分：开源仓库怎么维护

### 2.1 你的仓库现在是什么状态

```
https://github.com/rei0-t/sql-agent
├── LICENSE             Apache-2.0（别人可以免费用、改、商用，但要保留版权声明）
├── README.md           门面：这东西是什么、怎么跑起来、截图
├── SECURITY.md         安全边界（"能防什么、不能防什么"写清楚，避免误报）
├── CONTRIBUTING.md     别人想帮你改代码时看
├── docs/               教程、部署、语义层示例
├── deploy/             部署相关的一切
└── Release v0.1.0      版本发布
```

### 2.2 日常要做的四件事

**① 改代码 → 推上去**

```powershell
cd E:\deepseekHarness\sql-agent
git add -A
git commit -m "fix: 一句话说清改了什么"
# 推不上去就用脚本（校园网会劫持 github.com）
backend\.venv\Scripts\python.exe scripts\publish_api.py --token <你的PAT> --repo sql-agent --message "fix: ..."
```

> 提交信息写法建议：`feat:` 新功能 / `fix:` 修 bug / `docs:` 文档 / `chore:` 杂活。
> 这条习惯在面试时会被看：**能看出你是不是真的在维护一个项目**。

**② 打版本号（有值得说的更新时）**

GitHub → Releases → Draft a new release → 选 `v0.1.1` → 写清楚这个版本改了什么。

打版本的意义：别人能下载到"某个确定的可用状态"，你也能随时回滚到它。

**③ 看看有没有人提 issue**

GitHub 页面顶部 Issues 标签。有人提就回，哪怕回"我先复现一下"。

**④ 别把密钥提交上去**

已经做过的防护：

```bash
# .gitignore 里忽略了这些
.env
backend/.env
backend/data/
deploy/aliyun/data/
```

**如果手滑提交了 Key**：立刻去控制台吊销那个 Key（换成新的），然后从 git 历史里删。**吊销比删历史重要**——历史可以慢慢清，Key 泄露是一秒钟的事。

### 2.3 README 该写什么（你已经有了）

| 段落 | 作用 |
|---|---|
| 一句话说明 | 别人 3 秒判断"我要不要看下去" |
| 截图 | 最有效的说服力 |
| 快速开始 | 三条命令能跑起来 |
| 架构/流程 | 让人相信你不是拼的 |
| 安全声明 | 提前说清楚边界，避免"你这个不安全"的指责 |
| 评测数据 | 用数字说话：准确率、耗时、token |

### 2.4 让别人能跑起来的三个层次

| 层次 | 门槛 | 你现在支持吗 |
|---|---|---|
| 本机跑 | 装 Python + Node | ✅ README 有 |
| Docker 跑 | 只要装 Docker | ✅ `deploy/docker-compose.yaml` |
| 云上一键 | 有台服务器 | ✅ `deploy/aliyun/install.sh` |

**这三层都通，是"能开源"和"只是把代码传上去"的区别。**

---

## 第三部分：部署上线（从零到能访问）

### 3.1 你需要准备什么

| 项 | 你的现状 |
|---|---|
| 服务器 | ✅ 阿里云 ECS，香港，2C4G，Ubuntu 22.04，IP `47.238.174.161` |
| 安全组 | ✅ 已放行 80 端口 |
| 域名 | ⬜ 还没买（可选，见 3.5） |
| 模型 Key | ✅ 已配好（百炼） |

### 3.2 部署（已经做过，这里留档）

```bash
# 登录服务器（控制台「远程连接 → Workbench」）
apt-get update -qq && apt-get install -y git
mkdir -p /opt && cd /opt && git clone https://github.com/rei0-t/sql-agent.git
cd /opt/sql-agent && bash deploy/aliyun/install.sh
```

脚本会自动做 7 件事：

1. 检查内存，2G 机器自动建 swap（防止构建时被 OOM 杀掉）
2. 装 Docker（走阿里云镜像源）
3. 装 Nginx
4. 生成 `.env.prod`（随机密码）
5. 构建镜像并启动容器
6. 配好 Nginx 反向代理
7. 自检并打印访问地址 + 初始密码

**成功标志**：屏幕上出现一个方框，里面有 `打开：http://IP/`、用户名、密码。

### 3.3 部署完之后必须做的三件事

**① 记住管理员密码**

```bash
grep SQLAGENT_ADMIN_PASSWORD /opt/sql-agent/.env.prod
```

**② 在网页里配模型 Key**

登录 → 左侧「设置」→ 填 Base URL / 模型名 / API Key → **先点「测试连接」**，成功再「保存」。

> 或者在 `.env.prod` 里写 `SQLAGENT_LLM_API_KEY=sk-xxx`（这样所有人默认用你的 Key，配合额度使用）。

**③ 灌一个演示库（可选）**

```bash
cd /opt/sql-agent && docker compose -f deploy/aliyun/docker-compose.prod.yaml --env-file .env.prod exec app python /app/scripts/seed_demo.py --out /app/backend/data/shop.db
```

然后在网页「数据源 → 新建 → SQLite → 服务器路径」填 `/app/backend/data/shop.db`。

> 注：现在新用户注册会自动获得「示例库（只读）」，这一步只是为了给你自己留一份可改的副本。

### 3.4 更新代码（最常做的操作）

```bash
cd /opt/sql-agent
git pull
bash deploy/aliyun/install.sh
```

- 有数据库结构变化时，容器启动会自动跑迁移
- `.env.prod` **不会被覆盖**（密码不变）
- 构建用的是 Docker 缓存，通常 1–3 分钟

**只改了 `.env.prod`**（不用重建镜像）：

```bash
cd /opt/sql-agent
docker compose -f deploy/aliyun/docker-compose.prod.yaml --env-file .env.prod up -d
```

### 3.5 配域名 + HTTPS（可选，20 分钟）

**为什么值得做**：`http://47.238.174.161` 放进简历很难看；而且没有 HTTPS，登录密码是明文传输的。

**要不要备案？** 你的服务器在**香港**，不需要。大陆节点才需要（1–2 周）。

**步骤：**

1. 买个域名（阿里云/腾讯云，¥30–60/年），解析到 `47.238.174.161`
2. 申请免费证书（阿里云「数字证书管理服务」→ 免费 DV 证书 → 下载 Nginx 格式）
3. 传上去并换配置：

```bash
sudo mkdir -p /etc/nginx/certs
sudo cp 你的证书.pem /etc/nginx/certs/sql-agent.pem
sudo cp 你的私钥.key /etc/nginx/certs/sql-agent.key

cd /opt/sql-agent
sudo cp deploy/aliyun/nginx-tls.conf /etc/nginx/conf.d/sql-agent.conf
sudo vim /etc/nginx/conf.d/sql-agent.conf    # 改 server_name 为你的域名
sudo nginx -t && sudo systemctl reload nginx
```

4. **关键一步**：打开 Secure cookie，否则 HTTPS 下登录会失效

```bash
sed -i 's/^SQLAGENT_COOKIE_SECURE=.*/SQLAGENT_COOKIE_SECURE=true/' /opt/sql-agent/.env.prod
cd /opt/sql-agent && docker compose -f deploy/aliyun/docker-compose.prod.yaml --env-file .env.prod up -d
```

5. 浏览器打开 `https://你的域名/` 验证

---

## 第四部分：日常运维（每天/每周/每月）

### 4.1 一页纸检查表

| 频率 | 做什么 | 命令 |
|---|---|---|
| **每天** | 看一眼服务活着 | `curl -s localhost:8080/api/v1/health` |
| **每天** | 看一眼有没有报错 | `docker compose ... logs --tail=50 app` |
| **每周** | 备份数据库 | `bash deploy/aliyun/backup.sh` |
| **每周** | 看磁盘还剩多少 | `df -h /` |
| **每月** | 清理旧审计 | `archive_audit.py --days 180` |
| **每月** | 看一眼额度用量 | `reset_quota.py --list` |
| **每月** | 更新系统补丁 | `apt update && apt upgrade -y` |
| **随时** | 有人问"我没次数了" | `reset_quota.py --workspace N` |

### 4.2 常用命令（存到备忘录里）

先定义两个缩写，后面都用它们：

```bash
cd /opt/sql-agent
alias dc='docker compose -f deploy/aliyun/docker-compose.prod.yaml --env-file .env.prod'
```

| 想干什么 | 命令 |
|---|---|
| 服务活着吗 | `curl -s localhost:8080/api/v1/health` |
| 容器状态 | `dc ps` |
| 实时看日志 | `dc logs -f app` |
| 看最后 100 行 | `dc logs --tail=100 app` |
| 重启应用 | `dc restart app` |
| 全停 | `dc down` |
| 全起 | `dc up -d` |
| 进容器里看看 | `dc exec app bash` |
| 备份 | `bash deploy/aliyun/backup.sh` |
| 磁盘占用 | `df -h /` 和 `docker system df` |
| 内存占用 | `free -h` |
| 谁在占 80 端口 | `ss -lntp | grep :80` |

### 4.3 备份与恢复（唯一不能省的事）

**备份**（每周一次，或改重大配置前）：

```bash
cd /opt/sql-agent
bash deploy/aliyun/backup.sh
# 产物：deploy/aliyun/backups/sqlagent-20261127-233000.sql.gz
```

**加个定时任务**（每天凌晨 3:20 自动备份，保留 14 天）：

```bash
crontab -e
# 加这一行（路径按你的实际情况）
20 3 * * * cd /opt/sql-agent && bash deploy/aliyun/backup.sh >> /var/log/sqlagent-backup.log 2>&1
```

**恢复**（换机器、误删时）：

```bash
gunzip -c deploy/aliyun/backups/sqlagent-xxx.sql.gz | \
  docker compose -f deploy/aliyun/docker-compose.prod.yaml --env-file .env.prod \
  exec -T db psql -U sqlagent -d sqlagent
```

**手工全量快照**（最省心，适合换机器）：

```bash
# 在旧机器上
tar -czf ~/sqlagent-data.tgz -C /opt/sql-agent deploy/aliyun/data
bash deploy/aliyun/backup.sh

# 在新机器上（按 3.2 部署完之后）
tar -xzf ~/sqlagent-data.tgz -C /opt/sql-agent
gunzip -c 备份.sql.gz | docker compose ... exec -T db psql -U sqlagent -d sqlagent
```

> ⚠️ 备份文件里有**加密后的**数据源口令，但没有 `SQLAGENT_SECRET_KEY` 就解不开。
> 所以**换机器时必须带上原来的 `.env.prod`**，否则数据源口令全部失效（账号还能用）。

### 4.4 修改常用配置

| 想改 | 改 `.env.prod` 里的 | 然后 |
|---|---|---|
| 关闭注册 | `SQLAGENT_ALLOW_REGISTRATION=false` | `dc up -d` |
| 每人提问次数 | `SQLAGENT_CHAT_MAX_QUESTIONS=10`（0=不限） | `dc up -d` |
| 换模型 | `SQLAGENT_LLM_MODEL=qwen-plus` | `dc up -d` |
| 换 Key | `SQLAGENT_LLM_API_KEY=sk-xxx` | `dc up -d` |
| 允许上传的文件总大小 | `SQLAGENT_UPLOAD_MAX_MB_TOTAL=4096` | `dc up -d` |
| 关掉上传 | `SQLAGENT_ALLOW_UPLOAD=false` | `dc up -d` |
| 上 HTTPS 后 | `SQLAGENT_COOKIE_SECURE=true` | `dc up -d` |

改完 `.env.prod` 后**必须**执行 `dc up -d`（或 `dc restart app`）才生效，因为环境变量是启动时读的。

### 4.5 审计与额度

```bash
# 看谁把额度用完了
dc exec app python /app/scripts/reset_quota.py --list

# 给某个工作空间清零
dc exec app python /app/scripts/reset_quota.py --workspace 3

# 归档 180 天前的审计（导出成文件再删）
dc exec app python /app/scripts/archive_audit.py --days 180

# 清理没有被任何数据源引用的上传文件
dc exec app python /app/scripts/cleanup_uploads.py          # 只列出
dc exec app python /app/scripts/cleanup_uploads.py --apply  # 真删
```

### 4.6 磁盘满了怎么办

```bash
df -h /                  # 看总占用
docker system df         # 看 Docker 占了多少
du -sh /opt/sql-agent/deploy/aliyun/data   # 上传的文件占了多少
```

**三种常见占用：**

| 占什么 | 清法 |
|---|---|
| 旧镜像 | `docker image prune -a`（谨慎，会删掉不用的镜像） |
| 日志 | compose 里已经限制了每个容器 20MB × 5 个文件，一般不会爆 |
| 上传文件 | 用 `cleanup_uploads.py`，或让用户在网页里删数据源（会自动删文件） |

---

## 第五部分：出问题怎么办

### 5.1 排障顺序（照这个顺序走，别跳）

```
1. 服务活着吗？   curl localhost:8080/api/v1/health
2. 容器在吗？     dc ps
3. 日志说什么？   dc logs --tail=100 app
4. Nginx 通吗？   curl -I localhost/
5. 端口通吗？     ss -lntp | grep -E ':(80|8080)'
```

### 5.2 症状对照表

| 症状 | 最可能的原因 | 怎么查 / 怎么修 |
|---|---|---|
| 浏览器打不开，一直转圈 | 阿里云安全组没放行 80 | 控制台 → 安全组 → 入方向加 `80/80` |
| 浏览器显示 502 Bad Gateway | 应用容器挂了 | `dc ps` → `dc logs --tail=100 app` → `dc restart app` |
| 能打开但登录报错 | 数据库没起来 | `dc ps` 看 db 是不是 healthy；`dc logs db` |
| 提问一直转圈不出字 | Nginx 把 SSE 缓冲了 | 确认配置里有 `proxy_buffering off;`（见 nginx-http.conf） |
| 提问报「未配置模型密钥」 | 没配 Key | 网页「设置」填 Key，或 `.env.prod` 加 `SQLAGENT_LLM_API_KEY` |
| 提问报「额度已用完」 | 该用户 5 次用完了 | `reset_quota.py --workspace N`，或让用户自己填 Key |
| 上传文件报 413 | Nginx 限制太小 | `client_max_body_size` 要 ≥ 应用上限（现在都是 64m） |
| 上传报「只支持 .db/.sqlite」 | 后缀不对 | 改名成 `.db` 再传 |
| 改完 `.env.prod` 没生效 | 没重启 | `dc up -d` |
| 换机器后数据源口令全失效 | 换了 `SQLAGENT_SECRET_KEY` | 必须沿用原来的 `.env.prod` |
| 磁盘满 / 服务莫名挂 | 日志或上传文件占满 | `df -h /`，按 4.6 清理 |
| `docker compose` 报 `port is already allocated` | 8080 被别的进程占了 | `ss -lntp \| grep 8080`，杀掉或改端口 |

### 5.3 回滚（改坏了想退回上一个版本）

```bash
cd /opt/sql-agent
git log --oneline -10          # 找到上一个好的提交
git checkout <那个提交的sha>
bash deploy/aliyun/install.sh   # 重新构建并启动
```

回滚完记得 `git checkout main` 回到主干，否则下次 `git pull` 会冲突。

### 5.4 什么时候该重启什么

| 情况 | 重启什么 |
|---|---|
| 改了 `.env.prod` | `dc up -d`（重建容器） |
| 改了 Nginx 配置 | `sudo nginx -t && sudo systemctl reload nginx` |
| 应用卡住 / 内存涨 | `dc restart app` |
| 服务器整体卡 | `sudo reboot`（先用 `dc ps` 确认容器会自动重启，compose 里配了 `restart: unless-stopped`） |

---

## 第六部分：费用与安全

### 6.1 钱花在哪

| 项 | 大概 | 说明 |
|---|---|---|
| ECS 2C4G（按量） | ¥0.3/小时 | 关机不计（只收云盘几毛钱/天） |
| 公网流量 | ¥0.5–1/GB | 网页很小，正常一个月几毛到几块 |
| 模型调用 | **主要开销** | 一次问答约 5k token |
| 域名（可选） | ¥30–60/年 | |
| 证书 | ¥0 | 阿里云有免费 DV |

**模型费用估算**（按 qwen-flash 档，具体以控制台价目为准）：

| 场景 | 一天 |
|---|---|
| 没人用 | ¥0 |
| 5 个人各问完 5 次 | 约 25 次 × 5k token ≈ 十几万 token，几毛钱 |
| 被爬虫刷 | 额度挡住了：每人 5 次封顶 |

> **额度是你唯一的护栏。** 不要在没有额度的前提下放公共 Key。

### 6.2 安全清单（上线前对着勾）

- [x] `SQLAGENT_SECRET_KEY` 是随机 64 位（install.sh 自动生成）
- [x] 管理员密码不是默认的 `sqlagent123`
- [x] 数据库只监听容器内网，不对公网开 3306/5432
- [x] 应用的 8080 只绑 `127.0.0.1`，外网只走 Nginx
- [x] 登录有失败限流（同一 IP / 同一用户名）
- [x] 注册有频率限制（5 个/小时/IP）
- [x] 会话是 httpOnly cookie + CSRF 双提交
- [ ] 上了域名后：`SQLAGENT_COOKIE_SECURE=true`
- [ ] 上了域名后：Nginx 里 `listen 443 ssl`（见 nginx-tls.conf）
- [ ] 定期备份 `pgdata`（见 4.3）

### 6.3 别人扫你服务器怎么办

公网机器每天都会被扫描，这是常态。判断标准：

| 现象 | 要不要管 |
|---|---|
| 日志里出现大量 `/wp-admin`、`/.env` 之类 404 | 不用管，正常的扫描噪音 |
| 有人尝试登录而且失败了 | 限流会挡住；审计里能看到 |
| 带宽/CPU 异常高 | 看 `dc logs`，可能是被刷了，临时 `SQLAGENT_ALLOW_REGISTRATION=false` |
| 想更稳 | 安全组把 80 只放给需要的来源；或上 Cloudflare |

---

## 第七部分：小白术语表

| 词 | 人话解释 |
|---|---|
| **ECS** | 阿里云的虚拟机，就是你租的一台云端电脑 |
| **安全组** | 这台机器的防火墙。默认什么都进不来，要手动放行端口 |
| **端口** | 一台机器上的"门牌号"。80 是网页，443 是加密网页，22 是远程登录 |
| **Nginx** | 站在最前面的接待员，负责把外部请求转给后面的程序 |
| **反向代理** | 就是上面那句话：外部看到的是 Nginx，真正的程序藏在后面 |
| **Docker** | 把程序和它的运行环境打包成"集装箱"，到哪都能一模一样地跑 |
| **镜像 / 容器** | 镜像 = 集装箱的图纸；容器 = 按图纸造出来的、正在跑的那个箱子 |
| **Docker Compose** | 用一个配置文件管理"多个集装箱"（你的 app + db） |
| **卷（volume）** | 容器的硬盘。容器删了卷还在，数据不会丢 |
| **SSH / Workbench** | 远程登录服务器的方式，Workbench 是网页版的 |
| **环境变量** | 启动程序时喂给它的配置，存在 `.env.prod` 里 |
| **git pull** | 把 GitHub 上的新代码拉到服务器上 |
| **迁移（migration）** | 数据库结构的版本管理，比如"加一个字段" |
| **备份** | 把数据库导出成一个 SQL 文件，出事能倒回去 |
| **域名解析** | 让 `sql-agent.xxx.com` 指向 `47.238.174.161` 这个 IP |
| **ICP 备案** | 大陆服务器的域名必须备案（1–2 周）。香港/海外不需要 |
| **HTTPS / 证书** | 加密传输。没有它，登录密码是明文在网上走的 |
| **SSE** | 一种"边算边推"的网页技术，让回答一个字一个字出现 |
| **Token** | 模型计费单位，1 个汉字约 1–2 个 token |

---

## 附录：把项目讲清楚（面试用）

> 面试官不会问"你部署到哪台机器"，但会问"你怎么保证它上线不出事"。

### 30 秒版本

> 我做了一个自然语言查数据的工具：用户用中文提问，它生成 SQL、在只读连接上执行、再用一句话给结论。
> 后端 FastAPI，前端 Vue，模型通过 OpenAI 兼容接口接的百炼。线上跑在阿里云 ECS 上，Docker + Nginx。

### 如果被追问，准备这四个点

**① 安全边界是怎么划的**

> 三道：执行端只用只读账号（SQLite 用 `mode=ro`）、SQL 闸门只放行单条 SELECT 并强制 LIMIT、
> 多租户按 workspace 隔离。注入我没吹"防住了"，而是写明"无法提权，但可能查错表"，
> 并给了 `injection_flags` 留痕和严格白名单开关。

**② 怎么知道它准不准**

> 20 题演示集，比的是结果集不是 SQL 文本。qwen-plus 100%、qwen-flash 90%。
> 我也明确说了这是对单库过拟合，不是泛化能力。

**③ 上线踩过什么坑**

> 部署这天修了这些：镜像漏了 `httpx` 依赖（构建期加 `import` 检查兜住）、
> Nginx 默认 4MB 限制把 50MB 上传卡成 413、logout 没走 CSRF 校验、
> 2G 机器构建镜像被 OOM 杀掉（脚本自动加 swap）。每个都有对应的提交和测试。

**④ 运维是怎么做的**

> 数据落在 Docker 卷 + 定时 `pg_dump`；升级走 `git pull && install.sh`，迁移在容器启动时自动跑；
> 额度/审计/清理都有脚本；监控目前是健康检查 + 日志，没上 Prometheus——**这是我知道的缺口**。

### 不要说

- ❌ "我用了最新最牛的技术栈"（面试官会追问细节）
- ❌ "这个很安全"（应该讲边界）
- ❌ "准确率 100%"（应该讲评测条件和局限）
- ✅ "这个我没做，因为 X 优先级更高，如果要做我会从 Y 开始"

---

## 附：文件地图

```
/opt/sql-agent/
├── .env.prod                        ← 配置（密码、Key、开关），权限 600，不进 git
├── deploy/aliyun/
│   ├── install.sh                   ← 一键部署/更新
│   ├── backup.sh                    ← 备份
│   ├── data/                        ← 上传的 SQLite 文件、示例库（要备份）
│   ├── backups/                     ← 备份产物
│   └── nginx-http.conf / nginx-tls.conf
└── backend/                         ← 后端代码

/etc/nginx/conf.d/sql-agent.conf     ← Nginx 站点配置
/var/lib/docker/volumes/...          ← PostgreSQL 数据（别碰）
```

---

**最后一句**：这份文档里所有命令都假设你在 `/opt/sql-agent` 目录下执行。
不确定自己在哪，先 `pwd`；不确定服务什么状态，先 `curl -s localhost:8080/api/v1/health`。