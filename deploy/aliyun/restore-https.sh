#!/usr/bin/env bash
# 恢复 HTTPS：把 nginx-tls.conf 渲染回 /etc/nginx/conf.d/。
#
#   sudo bash deploy/aliyun/restore-https.sh [域名]
#
# 什么时候用：跑过 install.sh 之后 443 不监听（install.sh 会把 Nginx 配置覆盖成
# HTTP 版），站点变成"拒绝连接"。这个脚本把 TLS 配置装回去，域名和证书路径
# 从 /etc/letsencrypt/live 自动推断，不用手填。
#
# 环境变量：
#   QUIET=1   少输出（install.sh 里调用时用）

set -euo pipefail

cd "$(dirname "$0")/../.."
ROOT="$(pwd)"
NGINX_CONF=/etc/nginx/conf.d/sql-agent.conf
LIVE_DIR=/etc/letsencrypt/live

DOMAIN="${1:-}"
QUIET="${QUIET:-0}"

say() { [[ "$QUIET" == "1" ]] || printf '\n\033[1m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33m!! %s\033[0m\n' "$1"; }
ok() { [[ "$QUIET" == "1" ]] || printf '    \033[32m✓\033[0m %s\n' "$1"; }

if [[ $EUID -ne 0 ]]; then
  echo "请用 root 运行：sudo bash deploy/aliyun/restore-https.sh" >&2
  exit 1
fi

# ---------- 1. 找到域名（优先参数，其次已有的证书目录） ----------
if [[ -z "$DOMAIN" ]]; then
  DOMAIN=$(ls "$LIVE_DIR" 2>/dev/null | grep -v -E '^(README|\.)' | head -n1 || true)
fi
if [[ -z "$DOMAIN" ]]; then
  warn "找不到可用证书（$LIVE_DIR 为空）。先用 HTTP 起站："
  warn "  sudo bash deploy/aliyun/install.sh"
  warn "再申请证书："
  warn "  sudo bash deploy/aliyun/enable-https.sh <域名> <邮箱>"
  exit 1
fi

CERT_DIR="$LIVE_DIR/$DOMAIN"
if [[ ! -f "$CERT_DIR/fullchain.pem" || ! -f "$CERT_DIR/privkey.pem" ]]; then
  warn "证书文件不全：$CERT_DIR"
  exit 1
fi
say "恢复 HTTPS：$DOMAIN"

# ---------- 2. 渲染配置 ----------
cp "$ROOT/deploy/aliyun/nginx-tls.conf" "$NGINX_CONF"
sed -i "s/sql-agent\.example\.com/$DOMAIN/g" "$NGINX_CONF"
sed -i "s#/etc/nginx/certs/sql-agent\.pem#$CERT_DIR/fullchain.pem#" "$NGINX_CONF"
sed -i "s#/etc/nginx/certs/sql-agent\.key#$CERT_DIR/privkey.pem#" "$NGINX_CONF"
mkdir -p /var/www/certbot
ok "已写入 $NGINX_CONF"

# ---------- 3. 校验并 reload ----------
if ! nginx -t; then
  warn "配置没通过，回退到 HTTP 版（站点至少还能用 80 访问）"
  cp "$ROOT/deploy/aliyun/nginx-http.conf" "$NGINX_CONF"
  nginx -t && systemctl reload nginx
  exit 1
fi
systemctl reload nginx
ok "Nginx 已 reload"

# ---------- 4. 自检 ----------
sleep 1
if curl -fsS --max-time 10 "https://$DOMAIN/api/v1/health" >/dev/null 2>&1; then
  ok "https://$DOMAIN/api/v1/health 正常"
else
  warn "https 健康检查没通过（域名可能还没解析到本机，或证书链有问题）"
  warn "  本机自测：curl -k --resolve $DOMAIN:443:127.0.0.1 https://$DOMAIN/api/v1/health"
  warn "  看日志：  tail -50 /var/log/nginx/error.log"
  exit 1
fi

# ---------- 5. 提醒 Secure cookie ----------
if grep -q '^SQLAGENT_COOKIE_SECURE=true' .env.prod 2>/dev/null; then
  ok "SQLAGENT_COOKIE_SECURE=true（已开）"
else
  warn "记得把 .env.prod 里的 SQLAGENT_COOKIE_SECURE 改成 true，否则 HTTPS 下登录会失效："
  warn "  sed -i 's/^SQLAGENT_COOKIE_SECURE=.*/SQLAGENT_COOKIE_SECURE=true/' .env.prod"
  warn "  docker compose -f deploy/aliyun/docker-compose.prod.yaml --env-file .env.prod up -d"
fi

if [[ "$QUIET" != "1" ]]; then
  cat <<EOF

============================================================
 HTTPS 已恢复： https://$DOMAIN/
 证书到期：$(openssl x509 -enddate -noout -in "$CERT_DIR/fullchain.pem" 2>/dev/null | cut -d= -f2 || echo 未知)
============================================================
EOF
fi