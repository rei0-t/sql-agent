# 部署说明

目标形态：一台能跑 Docker 的机器 + 一个域名（可选）。整个应用是**单进程**：FastAPI 同时提供 API 与前端静态文件。

## 1. 单机（最小可用）

```bash
git clone <your-repo> && cd sql-agent
cp .env.example .env
```

`.env` 里只需要改两个值：

```ini
SQLAGENT_SECRET_KEY=<用 openssl rand -hex 32 生成>
SQLAGENT_ADMIN_PASSWORD=<你的管理员口令>
```

```bash
docker compose -f deploy/docker-compose.yaml up -d --build
```

- 应用：`http://<host>:8080`
- 元数据库：compose 内置的 PostgreSQL 16（数据在 `pgdata` volume）
- 模型 Key：**不要写进 .env**，登录后在「设置」页填，加密落在元数据库里

## 2. 加 HTTPS（Caddy 反代）

Caddy 会自动申请证书，三行配置：

```caddyfile
sql-agent.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

```bash
docker run -d --name caddy --network host \
  -v $PWD/Caddyfile:/etc/caddy/Caddyfile \
  -v caddy_data:/data caddy:2
```

注意：SSE 需要关掉反代缓冲。Caddy 默认会透传；用 Nginx 时请加：

```nginx
proxy_buffering off;
proxy_read_timeout 300s;
```

## 3. 备份与升级

```bash
# 元数据库（配置、数据源、审计、Key）—— 这是唯一需要备份的东西
docker compose -f deploy/docker-compose.yaml exec db \
  pg_dump -U sqlagent sqlagent > backup-$(date +%F).sql

# 升级
git pull && docker compose -f deploy/docker-compose.yaml up -d --build
```

目标数据库本身不归这个应用管，不需要在这里备份。

## 4. 安全清单

上线前逐条确认：

- [ ] `SQLAGENT_SECRET_KEY` 已改（它同时用于登录令牌和数据源口令加密；**换了以后已存的口令无法解密**）
- [ ] `SQLAGENT_ADMIN_PASSWORD` 已改，不是默认的 `sqlagent123`
- [ ] 接入的目标库用的是**只读账号**，不是 root / superuser
- [ ] 8080 不直接暴露公网，或者前面有 HTTPS 反代
- [ ] 知道这个应用能看到目标库的哪些表（默认全库可读；库里有敏感表就不要接）
- [ ] 日志里不会打印模型 Key 与数据库口令（默认不打印；自定义日志时注意）

## 5. 资源占用

- 镜像约 300 MB（Python 3.12 + Node 构建产物）
- 空载内存 ~120 MB；一次问答峰值 ~200 MB
- 磁盘：元数据库很小（每千次问答约 2 MB 审计日志）

## 6. 已知限制

- 没有做多副本：SQLite 作元数据库时只能单实例；换 PostgreSQL 后仍建议单实例（SSE + 会话无状态，但没必要）
- 没有迁移工具（Alembic 在 Roadmap 里）：升级前后建议先 `pg_dump`
- 没有内置限流：公网部署时在反代层加 `limit_req`