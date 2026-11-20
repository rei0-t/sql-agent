# 贡献指南

## 开发环境

- Python ≥ 3.11（后端），Node ≥ 20 + pnpm（前端）
- 本地开发默认用 SQLite 存元数据，不需要额外起数据库

```bash
cd backend && python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q && ruff check .
```

## 提交前请自检

1. `pytest -q` 全绿；新增接口必须有测试。
2. `ruff check .` 无告警。
3. **涉及 SQL 执行的改动**：必须同时在「只读」和「变更」两条路径上补测试，尤其是拒绝路径
   （越权表、无 WHERE 的 UPDATE、多语句、非 SELECT 语句）。
4. **不要提交真实数据库凭证、日志、`.env`**。示例数据用 `scripts/seed_demo.py` 生成。

## 提交信息

采用 Conventional Commits：`feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`。
一个提交只做一件事。

## 分支与 PR

- 从 `main` 切 `feat/<简短描述>`；
- PR 描述里写：动机、改动点、如何验证（贴命令或截图）；
- 涉及行为变更的，同步更新 `README.md` 的 Roadmap 或文档。

## 新增数据库方言

在 `backend/app/dialects.py` 里新增一个 `Dialect` 子类并注册到 `_DIALECTS`，实现：

- `dsn()` / `create_engine()`
- `server_version()`
- `row_counts()`（没有统计信息表就返回空字典，不要做全表 COUNT）

然后在 `backend/tests/` 里补一个基于容器的集成测试（可用 `testcontainers`），并更新 README 的支持矩阵。

## 许可证

贡献即表示你同意以 [Apache-2.0](LICENSE) 授权你的代码。

> 注意：本项目在功能上参考了同领域的其他开源项目（如 DataEase SQLBot），但代码是独立实现的。
> 请勿把 GPL 系项目的代码复制进本仓库，那会让整个项目的许可证失效。