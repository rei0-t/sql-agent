#!/bin/sh
# 容器入口：先迁移，再启动。
#
# 为什么迁移放在这里而不是 Dockerfile 的 RUN：
#   - 构建镜像时数据库还不存在（compose 里 db 是独立容器）
#   - 每次重启都跑一遍是安全的：alembic 的 upgrade 是幂等的，已是最新就什么都不做
#
# 迁移失败就退出（set -e），让编排层看到 unhealthy，而不是带着半截 schema 提供服务。

set -eu

echo "[entrypoint] 数据库迁移"
python /app/scripts/migrate.py

echo "[entrypoint] 启动 uvicorn :8080"
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8080 \
    --proxy-headers \
    --forwarded-allow-ips='*'