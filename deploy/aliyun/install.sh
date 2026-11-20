#!/usr/bin/env bash
# 一键安装：装 Docker、生成配置、构建、启动、自检。
#
#   sudo bash deploy/aliyun/install.sh
#
# 不做的事：不买机器、不改安全组、不配域名。这三件在阿里云控制台点。
# 已经存在 .env.prod 时不会覆盖（重复执行是安全的）。

set -euo pipefail

cd "$(dirname "$0")/../.."
ROOT="$(pwd)"
COMPOSE_FILE="deploy/aliyun/docker-compose.prod.yaml"
GENERATED=0

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

if [[ $EUID -ne 0 ]]; then
  echo "请用 root 运行：sudo bash deploy/aliyun/install.sh" >&2
  exit 1
fi

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
  apt-get update -qq && apt-get install -y docker-compose-plugin
fi

# ---------- 2. 配置 ----------
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

# ---------- 3. 构建启动 ----------
say "构建并启动（首次 3-6 分钟，会刷很多屏，正常）"
docker compose -f "$COMPOSE_FILE" --env-file .env.prod up -d --build

# ---------- 4. 健康检查 ----------
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
  echo "!! 服务没起来，看日志："
  docker compose -f "$COMPOSE_FILE" --env-file .env.prod logs --tail=60 app
  exit 1
fi

# ---------- 5. 汇总 ----------
PUBLIC_IP=""
for meta in public-ipv4 eipv4; do
  PUBLIC_IP=$(curl -fsS --max-time 2 "http://100.100.100.200/latest/meta-data/$meta" 2>/dev/null || true)
  [[ -n "$PUBLIC_IP" ]] && break
done
[[ -z "$PUBLIC_IP" ]] && PUBLIC_IP="<你的公网IP>"

ADMIN_PW_SHOW=$(grep '^SQLAGENT_ADMIN_PASSWORD=' .env.prod | cut -d= -f2)

cat <<EOF

============================================================
 部署完成
============================================================
 打开：      http://${PUBLIC_IP}:8080
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