# ---------- 前端构建 ----------
FROM node:22-alpine AS web

# 国内 ECS 上默认走 npmmirror；在海外构建时用 --build-arg NPM_REGISTRY=https://registry.npmjs.org 覆盖
ARG NPM_REGISTRY=https://registry.npmmirror.com

WORKDIR /web
COPY frontend/ ./
RUN corepack enable \
    && pnpm config set registry "$NPM_REGISTRY" \
    && (pnpm install --frozen-lockfile || pnpm install --no-frozen-lockfile) \
    && pnpm build

# ---------- 运行时 ----------
FROM python:3.12-slim AS runtime

# 国内 ECS 上默认走阿里云 PyPI 镜像；海外可用 --build-arg PIP_INDEX_URL=https://pypi.org/simple 覆盖
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SQLAGENT_DATA_DIR=/app/backend/data

WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY scripts ./scripts
RUN pip install -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" .

COPY --from=web /web/dist /app/frontend/dist

RUN useradd --create-home --uid 10001 sqlagent \
    && mkdir -p /app/backend/data \
    && chown -R sqlagent:sqlagent /app
USER sqlagent

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health', timeout=2)" || exit 1

# --proxy-headers：让反向代理传来的 X-Forwarded-* 生效（日志里的客户端 IP 才是真的）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]