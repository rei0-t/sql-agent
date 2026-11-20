# 部署到阿里云 ECS

目标：一台 ECS + 一个可选域名，跑起「登录 → 设置模型 → 加数据源 → 提问」全流程。

```
公网 → Nginx(443) → 127.0.0.1:8080 → 容器内 FastAPI → 你的数据库
                                        └→ PostgreSQL 容器（元数据）
```

## 0. 先决定：用不用域名（这一步决定工期）

| 方案 | 备案 | 工期 | 适用 |
|---|---|---|---|
| **IP:8080 直接访问** | 不需要 | 当天 | 自己用、内部试用 |
| **域名 + 大陆节点（杭州/上海/北京）** | **必须 ICP 备案** | 备案 1–2 周（阿里云代备案） | 对外正式服务 |
| **域名 + 香港/新加坡节点** | 不需要 | 当天 | 想在境外起、不想备案 |

> 大陆节点的 80/443 端口对**未备案域名**会被拦截，这是硬规则，绕不过去。
> 建议：先用 ECS 公网 IP 跑起来（今天就能用），备案走流程，批下来再把域名指过来。

## 1. 买机器

| 项 | 建议值 | 说明 |
|---|---|---|
| 规格 | `2 vCPU / 4 GiB`（ecs.e-c1m2.large 或 u1-c1m2） | 1C2G 也能跑，但构建镜像时会很卡 |
| 镜像 | Ubuntu 22.04 LTS 64 位 | 脚本按这个写的 |
| 系统盘 | 40 GiB ESSD | 镜像 + 数据足够 |
| 地域 | 杭州 / 上海（离你近、离 DashScope 近） | 模型调用延迟低 |
| 带宽 | 按量 5 Mbps 起步 | 都是 JSON 接口，不吃带宽 |
| 公网 IP | 勾选分配 | |

成本粗算（按量/包月，以控制台为准）：ECS 2C4G 约 ¥90–150/月，带宽 5Mbps 按量约 ¥30–60/月，
云盘 40G 约 ¥10/月。域名 ¥30–60/年，备案免费。

## 2. 安全组（只开三个口）

| 端口 | 来源 | 用途 |
|---|---|---|
| 22 | **你的出口 IP**/32 | SSH，不要开 0.0.0.0/0 |
| 80 | 0.0.0.0/0 | HTTP（跳 HTTPS / 证书校验） |
| 443 | 0.0.0.0/0 | HTTPS |

**不要开 8080**：应用只绑 `127.0.0.1:8080`，对外统一走 Nginx。
数据库端口不要开放（compose 内部网络访问，本来也没映射）。

## 3. 装环境

```bash
# 在 ECS 上
sudo apt-get update && sudo apt-get install -y git nginx
git clone <你的仓库地址> /opt/sql-agent
cd /opt/sql-agent

# 装 Docker + 配阿里云镜像加速（MIRROR_ID 从「容器镜像服务 → 镜像加速器」拿）
sudo MIRROR_ID=你的ID bash deploy/aliyun/bootstrap.sh
```

## 4. 配置并启动

```bash
cd /opt/sql-agent

cp deploy/aliyun/.env.prod.example .env.prod
openssl rand -hex 32                     # 把输出填进 SQLAGENT_SECRET_KEY
vim .env.prod                            # 再填 SQLAGENT_ADMIN_PASSWORD、POSTGRES_PASSWORD

cp docs/semantics.example.yaml deploy/aliyun/data/semantics.yaml

docker compose -f deploy/aliyun/docker-compose.prod.yaml --env-file .env.prod up -d --build
curl -s localhost:8080/api/v1/health     # {"status":"ok","version":"0.1.0","database":"ok"}
```

首次构建 3–6 分钟（要拉 node/python 基础镜像并装依赖）。之后改代码只需 `up -d --build`。

## 5. 配 Nginx + HTTPS

```bash
# 1) 申请证书：阿里云「数字证书管理服务」→ 免费证书（DV）→ 下载 Nginx 格式
sudo mkdir -p /etc/nginx/certs
sudo cp 你的证书.pem /etc/nginx/certs/sql-agent.pem
sudo cp 你的私钥.key /etc/nginx/certs/sql-agent.key

# 2) 放配置
sudo cp deploy/aliyun/nginx-sql-agent.conf /etc/nginx/conf.d/sql-agent.conf
sudo vim /etc/nginx/conf.d/sql-agent.conf     # 改 server_name 与证书路径
sudo nginx -t && sudo systemctl reload nginx
```

**没有域名怎么办**：跳过这一步，先把安全组的 8080 对自己 IP 放开，直接
`http://<公网IP>:8080` 用；或者用 Nginx 自签证书 + IP 访问（浏览器会报不安全）。

> ⚠️ SSE 一定要走配置里那段 `location = /api/v1/chat/stream`（关了 `proxy_buffering`）。
> 用别的反代（Caddy/Cloudflare）也要关缓冲，否则前端要等整段回答生成完才一次性显示。

## 6. 首次登录后做三件事

1. **设置 → 模型**：填 DashScope 的 Base URL、`qwen-plus`、你的 API Key → 测试连接 → 保存
   （Key 加密入库，只回显末四位；不写进 `.env`）
2. **数据源 → 新建**：填目标库的**只读账号**。生产库别用 superuser
3. **设置 → 开发者 API Key**：如果要用 `/api/v1/query`，在这里建一个，明文只显示一次

## 7. 运维

```bash
# 日志
docker compose -f deploy/aliyun/docker-compose.prod.yaml logs -f app
docker compose -f deploy/aliyun/docker-compose.prod.yaml logs -f db

# 备份元数据库（配置/数据源/审计/Key 都在这）
bash deploy/aliyun/backup.sh
# 加到 crontab，每天 03:20
( crontab -l 2>/dev/null; echo "20 3 * * * cd /opt/sql-agent && bash deploy/aliyun/backup.sh >> /var/log/sql-agent-backup.log 2>&1" ) | crontab -

# 升级并回滚
git pull
IMG=sql-agent:$(date +%Y%m%d) docker compose ... up -d --build   # 或者先打 tag 再切 IMAGE_TAG
```

## 8. 上线前自检

```bash
curl -s https://你的域名/api/v1/health
curl -s -o /dev/null -w '%{http_code}\n' https://你的域名/            # 200
curl -s -o /dev/null -w '%{http_code}\n' https://你的域名/api/v1/datasources   # 401（未登录）
```

浏览器里点一遍：登录 → 设置里「测试连接」成功 → 数据源测试连接成功 → 对话问一句能出结果。
特别确认**流式效果**：问题发出后应该先看到「读取表结构 / 编写 SQL」，而不是白屏等十秒。

## 9. 这个部署没做的事

- **没有多副本 / 负载均衡**：单机够用；要横向扩时元数据库换 RDS，并把语义层与审计做成共享存储
- **没有 Alembic 迁移**：升级前先 `backup.sh`
- **没内置限流**：公网暴露时在 Nginx 加 `limit_req_zone`，或套阿里云 WAF
- **审计日志会一直长**：目前没有清理任务，量大时加定时归档

## 常见问题

| 现象 | 原因 |
|---|---|
| 构建卡在 `pnpm install` | 没配镜像加速，或 Docker Hub 被限速；重跑 `bootstrap.sh` 带 MIRROR_ID |
| 打开页面 502 | app 容器没起来：`docker compose ... logs app`，多半是 `.env.prod` 少了必填项 |
| 提问一直转圈 | Nginx 没关 `proxy_buffering`，或模型 Key 无效（设置页点「测试连接」看具体报错） |
| 登录 401 但密码没错 | 元数据库换了实例但 `SECRET_KEY` 没同步（令牌签名对不上） |
| 域名打不开但 IP 能开 | 大陆节点未备案 |