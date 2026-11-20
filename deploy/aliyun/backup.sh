#!/usr/bin/env bash
# 备份元数据库（配置、数据源、审计、API Key 全在里面）。
# 目标数据库本身不归这个应用管，不需要在这里备份。
#
# 用法：
#   bash deploy/aliyun/backup.sh                 # 写到 deploy/aliyun/backups/
#   KEEP_DAYS=30 bash deploy/aliyun/backup.sh    # 保留 30 天
#
# 建议加到 crontab（每天 03:20）：
#   20 3 * * * cd /opt/sql-agent && bash deploy/aliyun/backup.sh >> /var/log/sql-agent-backup.log 2>&1

set -euo pipefail

cd "$(dirname "$0")/../.."

COMPOSE="docker compose -f deploy/aliyun/docker-compose.prod.yaml"
ENV_FILE="${ENV_FILE:-.env.prod}"
OUT_DIR="${OUT_DIR:-deploy/aliyun/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"

echo "==> 导出元数据库"
$COMPOSE --env-file "$ENV_FILE" exec -T db \
  pg_dump -U sqlagent -d sqlagent --clean --if-exists \
  > "$OUT_DIR/sqlagent-$STAMP.sql"

gzip -f "$OUT_DIR/sqlagent-$STAMP.sql"
SIZE=$(du -h "$OUT_DIR/sqlagent-$STAMP.sql.gz" | cut -f1)
echo "    ok  $OUT_DIR/sqlagent-$STAMP.sql.gz  ($SIZE)"

echo "==> 清理 ${KEEP_DAYS} 天前的备份"
find "$OUT_DIR" -name 'sqlagent-*.sql.gz' -mtime "+$KEEP_DAYS" -print -delete || true

echo "==> 完成"
echo "    恢复到新库：gunzip -c <备份文件> | $COMPOSE --env-file $ENV_FILE exec -T db psql -U sqlagent -d sqlagent"