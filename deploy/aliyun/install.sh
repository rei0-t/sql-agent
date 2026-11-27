#!/usr/bin/env bash
# 一键上线：装 Docker + Nginx、生成配置、构建、启动、反代、自检。
#
#   sudo bash deploy/aliyun/install.sh
#
# 做完之后 http://<公网IP>/ 就能打开（80 端口由 Nginx 接，8080 只监听本机）。
# 不做的事：不买机器、不改安全组。这两件在阿里云控制台点（见 START-HERE.md）。
#
# 重复执行是安全的：已存在的 .env.prod 不会被覆盖，Nginx 配置会被更新。

set -euo pipefail

cd "$(dirname "$0")/../.."
ROOT="$(pwd)"
COMPOSE_FILE="deploy/aliyun/docker-compose.prod.yaml"
GENERATED=0

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33m!! %s\033[0m\n' "$1"; }

if [[ $EUID -ne 0 ]]; then
  echo "请用 root 运行：sudo bash deploy/aliyun/install.sh" >&2
  exit 1
fi

# ---------- 包管理器 ----------
if command -v apt-get >/dev/null 2>&1; then
  PKG=apt
elif command -v dnf >/dev/null 2>&1; then
  PKG=dnf
elif command -v yum >/dev/null 2>&1; then
  PKG=yum
else
  echo "认不出包管理器（需要 apt / dnf / yum 之一）" >&2
  exit 1
fi

install_pkg() {
  case "$PKG" in
    apt) apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" ;;
    dnf) dnf install -y "$@" ;;
    yum) yum install -y "$@" ;;
  esac
}

# ---------- 1. Docker ----------
say "检查 Docker"
if ! command -v docker >/dev/null 2>&1; then
  echo "    未安装，开始安装（国内镜像源，2-3 分钟）"
  curl -fsSL https://get.docker.com | sh -s -- --mirror Aliyun
  systemctl enable --now docker
else
  echo "    已安装：$(docker --version)"
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "    安装 compose 插件"
  install_pkg docker-compose-plugin || install_pkg docker-compose
fi

# ---------- 2. Nginx ----------
say "检查 Nginx"
if ! command -v nginx >/dev/null 2>&1; then
  install_pkg nginx
  systemctl enable --now nginx
else
  echo "    已安装：$(nginx -v 2>&1)"
fi

# ---------- 3. 配置 ----------
say "准备配置 .env.prod"
if [[ -f .env.prod ]]; then
  echo "    已存在，保持不变（想重新生成就删掉它）"
else
  SECRET=$(openssl rand -hex 32)
  ADMIN_PW=$(openssl rand -hex 6)
  PG_PW=$(openssl rand -hex 16)
  cat > .env.prod <<EOF
SQLAGENT_SECRET_KEY=$SECRET
SQLAGENT_ADMIN_PASSWORD=$ADMIN_PW
POSTGRES_PASSWORD=$PG_PW
SQLAGENT_ALLOW_REGISTRATION=true
# 接了 HTTPS 之后改成 true（浏览器才会在 https 下发送会话 cookie）
SQLAGENT_COOKIE_SECURE=false
SQLAGENT_STRICT_TABLE_ALLOWLIST=false
IMAGE_TAG=latest
EOF
  chmod 600 .env.prod
  GENERATED=1
  echo "    已生成（权限 600，不进 git）"
fi

mkdir -p deploy/aliyun/data
if [[ ! -f deploy/aliyun/data/semantics.yaml ]]; then
  cp docs/semantics.example.yaml deploy/aliyun/data/semantics.yaml
  echo "    语义层模板已放到 deploy/aliyun/data/semantics.yaml（按你的库改它）"
fi

# 容器以 uid 10001 运行，挂载目录必须让它可写
chown -R 10001:10001 deploy/aliyun/data
chmod 750 deploy/aliyun/data

# ---------- 4. 构建启动 ----------
say "构建并启动（首次 3-6 分钟，会刷很多屏，正常）"
docker compose -f "$COMPOSE_FILE" --env-file .env.prod up -d --build

# ---------- 5. Nginx 反代 ----------
say "配置 Nginx 反向代理"
if [[ -d /etc/nginx/conf.d ]]; then
  TARGET=/etc/nginx/conf.d/sql-agent.conf
  # Debian/Ubuntu 的默认站点会抢 80 端口的 default_server
  rm -f /etc/nginx/sites-enabled/default
else
  TARGET=/etc/nginx/nginx.conf
  warn "找不到 /etc/nginx/conf.d，跳过反代，请按 deploy/aliyun/nginx-http.conf 手动配置"
  TARGET=""
fi

if [[ -n "$TARGET" ]]; then
  cp deploy/aliyun/nginx-http.conf "$TARGET"
  if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx
    echo "    已写入 $TARGET 并 reload"
  else
    warn "nginx -t 没通过，配置保留了但没生效："
    nginx -t || true
  fi
fi

# ---------- 6. 防火墙 ----------
say "检查本机防火墙"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null 2>&1 || true
  ufw allow 443/tcp >/dev/null 2>&1 || true
  echo "    ufw 已放行 80/443"
elif command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-service=http >/dev/null 2>&1 || true
  firewall-cmd --permanent --add-service=https >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
  echo "    firewalld 已放行 http/https"
else
  echo "    没有启用的本机防火墙，跳过"
fi

# ---------- 7. 健康检查 ----------
say "等待服务就绪"
READY=0
for _ in $(seq 1 40); do
  if curl -fsS --max-time 2 http://127.0.0.1:8080/api/v1/health >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 3
done

if [[ $READY -ne 1 ]]; then
  echo "!! 应用没起来，看日志："
  docker compose -f "$COMPOSE_FILE" --env-file .env.prod logs --tail=80 app
  exit 1
fi

VIA_NGINX=0
if [[ -n "$TARGET" ]] && curl -fsS --max-time 3 http://127.0.0.1/api/v1/health >/dev/null 2>&1; then
  VIA_NGINX=1
fi

# ---------- 8. 汇总 ----------
PUBLIC_IP=""
for meta in public-ipv4 eipv4; do
  PUBLIC_IP=$(curl -fsS --max-time 2 "http://100.100.100.200/latest/meta-data/$meta" 2>/dev/null || true)
  [[ -n "$PUBLIC_IP" ]] && break
done
[[ -z "$PUBLIC_IP" ]] && PUBLIC_IP="<你的公网IP>"

ADMIN_PW_SHOW=$(grep '^SQLAGENT_ADMIN_PASSWORD=' .env.prod | cut -d= -f2)

if [[ $VIA_NGINX -eq 1 ]]; then
  URL="http://${PUBLIC_IP}/"
  NOTE="（如果打不开，先去控制台把安全组 80 端口放开）"
else
  URL="http://${PUBLIC_IP}:8080/"
  NOTE="（Nginx 没接上，暂时直连 8080；同时要在安全组放行 8080）"
fi

cat <<EOF

============================================================
 部署完成
============================================================
 打开：      ${URL}
 ${NOTE}
 用户名：    admin
 密码：      ${ADMIN_PW_SHOW}
 配置文件：  ${ROOT}/.env.prod
 数据目录：  ${ROOT}/deploy/aliyun/data

 第一步做什么：
   登录 → 左侧「设置」→ 填模型 API Key → 点「测试连接」→ 保存
   然后「数据源」→ 新建 → 填只读账号

 常用命令：
   cd ${ROOT}
   docker compose -f ${COMPOSE_FILE} --env-file .env.prod ps
   docker compose -f ${COMPOSE_FILE} --env-file .env.prod logs --tail=100 app
   bash deploy/aliyun/backup.sh

 换域名 + HTTPS：
   看 deploy/aliyun/README.md 第 5 节（换 nginx-tls.conf，并把
   .env.prod 里的 SQLAGENT_COOKIE_SECURE 改成 true 后重启）
============================================================
EOF

if [[ "$GENERATED" -eq 0 ]]; then
  echo "（配置是之前生成的，密码见 .env.prod 里的 SQLAGENT_ADMIN_PASSWORD）"
fi

if grep -q '^SQLAGENT_LLM_API_KEY=.\+' .env.prod 2>/dev/null; then
  echo
  echo "⚠ .env.prod 里配了公共模型 Key。如果你开放了注册，所有人都会花你的额度。"
  echo "  想让大家自带 Key：删掉 SQLAGENT_LLM_API_KEY 这一行并重启。"
fi