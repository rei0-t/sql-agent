# 从零开始：把 SQL-agent 跑到阿里云上

> 这份文档假设你**没碰过 Linux 服务器**。每一步都写清楚点哪里、粘贴什么、看到什么算成功。
> 全程不用域名、不用备案，目标是**今天就能用**。域名和 HTTPS 等跑通之后再说。

---

## 第 1 步：买一台服务器（约 5 分钟）

阿里云控制台 → 搜索「云服务器 ECS」→ **创建实例**

| 选项 | 选什么 |
|---|---|
| 付费模式 | **按量付费**（先试，几毛钱一小时） |
| 地域 | 华东1（杭州）或华北2（北京） |
| 实例规格 | **2 核 2 GiB 起**（经济型 e / u1 都行）。2G 够用，脚本会自动加 2G swap；预算宽裕选 4G，构建快一倍 |
| 镜像 | **Ubuntu 22.04 64位** |
| 系统盘 | 40 GiB ESSD |
| 公网 IP | 勾选「分配公网 IPv4 地址」，带宽计费「按使用流量」，峰值 5 Mbps |
| 登录凭证 | **自定义密码**，设一个你记得住的 root 密码 |

创建完等 1 分钟，实例状态变成「运行中」。记下**公网 IP**（形如 `47.96.12.34`）。

---

## 第 2 步：开放 80 端口（约 1 分钟）

ECS 控制台 → 点实例名 → **安全组** → 「配置规则」→ **入方向** → 「手动添加」：

| 端口范围 | 授权对象 | 说明 |
|---|---|---|
| `80/80` | `0.0.0.0/0` | 网页访问（Nginx 入口） |

> 22 端口（远程连接）默认已开，不用动。
> **8080 不需要对外开放**：应用只监听 127.0.0.1，外面统一走 Nginx。
> 以后上了 HTTPS，再加一条 `443/443`。

---

## 第 3 步：用网页终端连上服务器（不用装任何软件）

ECS 控制台 → 实例列表 → 右侧「**远程连接**」→ 选「**Workbench 远程连接**」→ 点「立即登录」
→ 如果提示输入密码，就填第 1 步设的 root 密码。

你会看到一个黑色窗口，最前面是 `root@iZ...:~#`。**接下来所有命令都粘贴到这里。**

---

## 第 4 步：上传安装包

在 Workbench 窗口右上角点「**文件**」→「**上传文件**」→ 选 `sql-agent.tar.gz` → 上传。

上传完成后，在黑色窗口里输入下面这行确认文件在不在：

```bash
ls -lh ~/sql-agent.tar.gz
```

能看到类似 `-rw-r--r-- 1 root root 348K ... sql-agent.tar.gz` 就对了。

---

## 第 5 步：两条命令（约 5 分钟）

```bash
mkdir -p /opt && tar -xzf ~/sql-agent.tar.gz -C /opt && cd /opt/sql-agent
sudo bash deploy/aliyun/install.sh
```

脚本会自动：装 Docker（国内镜像源）→ 生成密码 → 构建镜像 → 启动 → 等健康检查通过 →
在屏幕上打印**网址、管理员密码、下一步怎么做**。

跑完你会看到一段方框，长这样：

```
============================================================
 部署完成
============================================================
 打开：      http://47.xx.xx.xx/
 用户名：    admin
 密码：      a1b2c3d4e5f6
```

**把这行密码记下来**，等会儿登录要用（也在 `/opt/sql-agent/.env.prod` 里）。

> 如果脚本中途报错，别慌，用下面这段手工版兜底（效果一样）：
>
> ```bash
> mkdir -p /opt && tar -xzf ~/sql-agent.tar.gz -C /opt && cd /opt/sql-agent
> curl -fsSL https://get.docker.com | sh -s -- --mirror Aliyun
> systemctl enable --now docker
> apt-get install -y docker-compose-plugin
> cat > .env.prod <<'EOF'
> SQLAGENT_SECRET_KEY=把上面我给的值粘贴到这里
> SQLAGENT_ADMIN_PASSWORD=把你想要的密码粘贴到这里
> POSTGRES_PASSWORD=把上面我给的值粘贴到这里
> EOF
> mkdir -p deploy/aliyun/data
> cp docs/semantics.example.yaml deploy/aliyun/data/semantics.yaml
> docker compose -f deploy/aliyun/docker-compose.prod.yaml --env-file .env.prod up -d --build
> ```

---

## 第 6 步：想立刻看到效果？灌一个演示库（30 秒）

没有现成数据库也能先玩。在同一个窗口里跑：

```bash
cd /opt/sql-agent
docker compose -f deploy/aliyun/docker-compose.prod.yaml --env-file .env.prod \
  exec app python scripts/seed_demo.py --out data/shop.db
```

看到 `已生成 data/shop.db (…KB, 20000 笔订单)` 就行。等会儿在网页里加数据源时：
**类型选 SQLite，文件路径填 `/app/backend/data/shop.db`**。

---

## 第 7 步：打开网页

浏览器输入：`http://你的公网IP/`（80 端口，Nginx 转发到应用）

- 用户名：`admin`
- 密码：第 5 步里 `SQLAGENT_ADMIN_PASSWORD` 那个值

> 页面上还有「还没有账号？创建一个」——那是给别人的入口：**每个注册的人都自动获得一个独立空间**，
> 看不到你的数据源、你的模型 Key 和你的审计记录。不想让人注册，就在 `.env.prod` 里加一行
> `SQLAGENT_ALLOW_REGISTRATION=false` 再重启。

登录后按顺序做三件事：

**① 配置模型**
左侧「设置」→ 模型 →
- Base URL 已经默认填好（通义千问兼容端点），不用改
- 模型名：`qwen-plus`
- API Key：去 [阿里云百炼控制台](https://bailian.console.aliyun.com/) 创建，粘贴进来
- 点「**测试连接**」，看到「连接成功 · xx ms」→ 点「**保存**」

**② 加数据源**
左侧「数据源」→「新建数据源」
- 有自己的 MySQL/PostgreSQL：填主机、端口、库名、**只读账号密码**
- 只想试效果：类型选 `SQLite`，文件路径填 `/app/backend/data/shop.db`

保存后点那一行的「**测试**」，看到「可用」就通了；点「结构」能看到表。

**③ 提问**
左侧「对话」→ 输入：`2026 年第三季度华东区的 GMV 是多少`
十几秒后应该出现：结论 + SQL + 结果表。

---

## 以后常用的四条命令

```bash
cd /opt/sql-agent

# 看服务是否在跑
docker compose -f deploy/aliyun/docker-compose.prod.yaml --env-file .env.prod ps

# 看日志（排查问题就看这个）
docker compose -f deploy/aliyun/docker-compose.prod.yaml --env-file .env.prod logs --tail=100 app

# 改了代码后重新构建
docker compose -f deploy/aliyun/docker-compose.prod.yaml --env-file .env.prod up -d --build

# 备份（元数据：账号、数据源、审计、API Key）
bash deploy/aliyun/backup.sh
```

---

## 照着做还不行？先看这张表

| 现象 | 原因 | 怎么办 |
|---|---|---|
| 浏览器打不开 IP | 安全组没开 80 | 回到第 2 步 |
| 浏览器一直转圈 | 容器还在启动 | 等 30 秒刷新；`ps` 看 app 是否 Up |
| 第 5 步报错 `port is already allocated` | 8080 被占 | `docker ps` 看有没有旧容器；`docker compose ... down` 再起来 |
| 构建卡在 `pnpm install` 很久 | 网络慢 | 耐心等，或重跑一次（有缓存会快） |
| 登录提示密码错误 | `.env.prod` 里的密码和你输入的不一致 | `cat .env.prod` 看一下 |
| 提问报「未配置模型密钥」 | 设置里没保存成功 | 回设置页点「测试连接」，成功后再「保存」 |
| 别人注册后问问题花的是我的钱 | 你在 `.env.prod` 里放了公共 API Key | 删掉 `SQLAGENT_LLM_API_KEY` 那一行，让用户各填各的；或直接关注册 |
| 提问一直转圈不出字 | 直接 IP 访问不会有这问题；配了 Nginx 才会 | 见 `nginx-http.conf` 里 SSE 那段（`proxy_buffering off`） |

---

## 开放给别人用之前，想清楚这一件事

你有两种模式，选一种：

**A. 只给自己/团队用**（推荐先这样）
- `.env.prod` 里加 `SQLAGENT_ALLOW_REGISTRATION=false`
- 只有 `admin` 能登录；需要更多账号时，目前没有管理界面，得手工建（后续版本补）

**B. 开放注册**（对外产品）
- 保持 `SQLAGENT_ALLOW_REGISTRATION=true`
- **千万不要**在 `.env.prod` 里填 `SQLAGENT_LLM_API_KEY`：那会让所有人共用你的额度。
  留空，让每个用户在「设置」里填自己的 Key（这就是 BYOK 的意义）
- 注册的人各自独立，互相看不到数据；但他们都能访问这台机器，建议加个访问频率限制

---

## 之后想加域名

1. 域名解析到这台机器的公网 IP
2. **大陆节点必须做 ICP 备案**（阿里云控制台搜「备案」，1–2 周），没备案域名打不开
3. 备案通过后，按 `deploy/aliyun/README.md` 第 5 节换 `nginx-tls.conf` + 证书，并把 `SQLAGENT_COOKIE_SECURE` 改成 true