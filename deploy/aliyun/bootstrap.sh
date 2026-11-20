#!/usr/bin/env bash
# 阿里云 ECS 首次初始化：装 Docker、配镜像加速、准备目录。
# 适用：Ubuntu 22.04 / 24.04（阿里云公共镜像）
#
# 用法：sudo bash deploy/aliyun/bootstrap.sh
# 跑之前请先读一遍——它只做四件事：
#   1) 装 docker + compose 插件
#   2) 写入镜像加速地址（需要你先把 <你的ID> 换成容器镜像服务控制台里的地址）
#   3) 建数据目录
#   4) 打印下一步命令

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "请用 sudo 运行" >&2
  exit 1
fi

MIRROR_ID="${MIRROR_ID:-}"   # 例：MIRROR_ID=abcd1234

echo "==> 安装 Docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
else
  echo "    已安装：$(docker --version)"
fi

if [[ -n "$MIRROR_ID" ]]; then
  echo "==> 配置镜像加速器"
  mkdir -p /etc/docker
  cat > /etc/docker/daemon.json <<JSON
{
  "registry-mirrors": ["https://${MIRROR_ID}.mirror.aliyuncs.com"],
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "5" }
}
JSON
  systemctl restart docker
else
  echo "!! 没有传 MIRROR_ID，跳过镜像加速（拉镜像会比较慢）"
  echo "   阿里云控制台 → 容器镜像服务 → 镜像工具 → 镜像加速器，拿到地址后："
  echo "   sudo MIRROR_ID=你的ID bash deploy/aliyun/bootstrap.sh"
fi

echo "==> 准备数据目录"
mkdir -p deploy/aliyun/data
chmod 750 deploy/aliyun/data

echo
echo "==> 下一步"
cat <<'NEXT'
  1) cp deploy/aliyun/.env.prod.example .env.prod && 编辑三个必填项
  2) cp docs/semantics.example.yaml deploy/aliyun/data/semantics.yaml
  3) docker compose -f deploy/aliyun/docker-compose.prod.yaml --env-file .env.prod up -d --build
  4) curl -s localhost:8080/api/v1/health     # 期望 {"status":"ok",...}
NEXT