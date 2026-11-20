# SQL-agent 前端
- 安装依赖：`pnpm install`（Node 18+）
- 本地开发：`pnpm dev`，访问 http://127.0.0.1:5173
- 构建：`pnpm build`（含 `vue-tsc --noEmit`，产物输出到 `dist/`）
- 代理：开发环境 `/api` 转发到 http://127.0.0.1:8080，生产环境由反向代理转发 `/api/v1`