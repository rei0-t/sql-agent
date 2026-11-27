#!/usr/bin/env bash
# 一条命令把站点切成 HTTPS。
#
#   sudo bash deploy/aliyun/enable-https.sh <域名> <邮箱>
#
# 做五件事：
#   1) 检查域名是否已经解析到这台机器
#   2) 用 Let's Encrypt（certbot）申请证书，自动续期
#   3) 换用 nginx-tls.conf，把域名和证书路径替换进去
#   4) 打开 Secure cookie（否则 HTTPS 下登录会失效）
#   5) 自检：https 健康检查 + 证书到期时间
#
# 可选环境变量：
#   STAGING=1   用 Let's Encrypt 测试环境（不消耗正式配额，浏览器会警告不受信）
#   SKIP_DNS=1  跳过 DNS 检查（域名还没生效时强行继续，一般不需要）

set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"

usage() {
  echo "用法：sudo bash deploy/aliyun/enable-https.sh <域名> <邮箱>" >&2
  echo "例如：sudo bash deploy/aliyun/enable-https.sh sql-agent.example.com me@example.com" >&2
  exit 1
}

[[ -z "$DOMAIN" || -z "$EMAIL" ]] && usage

cd "$(dirname "$0")/../.."
ROOT="$(pwd)"
COMPOSE_FILE="deploy/aliyun/docker-compose.prod.yaml"
NGINX_CONF=/etc/nginx/conf.d/sql-agent.conf
WEBROOT=/var/www/certbot

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33m!! %s\033[0m\n' "$1"; }

if [[ $EUID -ne 0 ]]; then
  echo "请用 root 运行：sudo bash deploy/aliyun/enable-https.sh $DOMAIN $EMAIL" >&2
  exit 1
fi

# ---------- 1. DNS 检查 ----------
say "检查域名解析"
PUBLIC_IP=""
for meta in public-ipv4 eipv4; do
  PUBLIC_IP=$(curl -fsS --max-time 2 "http://100.100.100.200/latest/meta-data/$meta" 2>/dev/null || true)
  [[ -n "$PUBLIC_IP" ]] && break
done
RESOLVED=$(getent hosts "$DOMAIN" | awk '{print $1}' | head -n1 || true)

echo "    域名 $DOMAIN 解析到: ${RESOLVED:-（无）}"
echo "    本机公网 IP:        ${PUBLIC_IP:-（读不到）}"

if [[ -z "$RESOLVED" ]]; then
  warn "域名还没解析。去域名控制台加一条 A 记录指向 $PUBLIC_IP，等 1-10 分钟再跑一次"
  [[ "${SKIP_DNS:-0}" == "1" ]] || exit 1
elif [[ -n "$PUBLIC_IP" && "$RESOLVED" != "$PUBLIC_IP" ]]; then
  warn "解析结果和本机 IP 不一致（可能是 CDN 或还没生效）"
  [[ "${SKIP_DNS:-0}" == "1" ]] || exit 1
else
  echo "    ✓ 解析正确"
fi

# ---------- 2. 确保 80 端口可用 + ACME 目录 ----------
say "准备验证目录"
mkdir -p "$WEBROOT"
# 先确保 Nginx 用的是「带 acme-challenge」的 HTTP 配置
cp deploy/aliyun/nginx-http.conf "$NGINX_CONF"
nginx -t >/dev/null 2>&1 || { warn "nginx 配置未通过，先修好再继续"; nginx -t; exit 1; }
systemctl reload nginx
echo "    ✓ 80 端口已就绪（/.well-known/acme-challenge/）"

# ---------- 3. 申请证书 ----------
say "申请证书（Let's Encrypt）"
if ! command -v certbot >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y certbot
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y certbot
  else
    yum install -y certbot
  fi
fi

STAGING_ARGS=()
if [[ "${STAGING:-0}" == "1" ]]; then
  STAGING_ARGS=(--staging)
  warn "使用测试环境：证书不受浏览器信任，只用来验证流程"
fi

certbot certonly --webroot -w "$WEBROOT" \
  -d "$DOMAIN" \
  --email "$EMAIL" \
  --agree-tos --no-eff-email \
  --non-interactive \
  "${STAGING_ARGS[@]}" \
  --keep-until-expiring

CERT_DIR="/etc/letsencrypt/live/$DOMAIN"
if [[ ! -f "$CERT_DIR/fullchain.pem" ]]; then
  warn "没找到证书：$CERT_DIR/fullchain.pem"
  exit 1
fi
echo "    ✓ 证书已签发：$CERT_DIR"

# ---------- 4. 换成 HTTPS 配置 ----------
say "切换 Nginx 到 HTTPS"
cp deploy/aliyun/nginx-tls.conf "$NGINX_CONF"
sed -i "s/sql-agent\.example\.com/$DOMAIN/g" "$NGINX_CONF"
sed -i "s#/etc/nginx/certs/sql-agent\.pem#$CERT_DIR/fullchain.pem#" "$NGINX_CONF"
sed -i "s#/etc/nginx/certs/sql-agent\.key#$CERT_DIR/privkey.pem#" "$NGINX_CONF"

if ! nginx -t; then
  warn "配置没通过，已回退到 HTTP 版"
  cp deploy/aliyun/nginx-http.conf "$NGINX_CONF"
  nginx -t && systemctl reload nginx
  exit 1
fi
systemctl reload nginx
echo "    ✓ 已切换到 HTTPS"

# ---------- 5. 打开 Secure cookie ----------
say "打开 Secure cookie"
if grep -q '^SQLAGENT_COOKIE_SECURE=' .env.prod 2>/dev/null; then
  sed -i 's/^SQLAGENT_COOKIE_SECURE=.*/SQLAGENT_COOKIE_SECURE=true/' .env.prod
else
  echo 'SQLAGENT_COOKIE_SECURE=true' >> .env.prod
fi
docker compose -f "$COMPOSE_FILE" --env-file .env.prod up -d
echo "    ✓ 应用已重启"

# ---------- 6. 自检 ----------
say "自检"
sleep 3
if curl -fsS --max-time 10 "https://$DOMAIN/api/v1/health" >/dev/null 2>&1; then
  echo "    ✓ https://$DOMAIN/api/v1/health 正常"
else
  warn "https 健康检查失败，看这里："
  warn "  docker compose -f $COMPOSE_FILE --env-file .env.prod logs --tail=40 app"
  warn "  tail -50 /var/log/nginx/error.log"
fi

EXPIRY=$(openssl x509 -enddate -noout -in "$CERT_DIR/fullchain.pem" 2>/dev/null | cut -d= -f2 || true)

cat <<EOF

============================================================
 HTTPS 已生效
============================================================
 地址：  https://$DOMAIN/
 证书到期：${EXPIRY:-未知}

 续期：certbot 会自动续（systemd 定时器），不用手动管。
       想手动测试续期：sudo certbot renew --dry-run

 回滚到 HTTP：
   sudo cp $ROOT/deploy/aliyun/nginx-http.conf $NGINX_CONF
   sudo nginx -t && sudo systemctl reload nginx
   sed -i 's/^SQLAGENT_COOKIE_SECURE=.*/SQLAGENT_COOKIE_SECURE=false/' .env.prod
   cd $ROOT && docker compose -f $COMPOSE_FILE --env-file .env.prod up -d
============================================================
EOF