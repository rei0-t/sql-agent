# P1 执行规格：只读通道（Query Plane）

> 目标：自然语言 → SQL → 在目标库上执行 → 结果表 + 一句话结论，**默认零写权限**。
> 验收：60 题读评测 EX ≥ 65%，20 条攻击载荷拦截率 100%，单问 p95 < 15s。

## 1. 新增/改动文件

```
backend/app/engine/
├── llm.py          # OpenAI 兼容客户端：重试、超时、token 统计（可注入 fake 做测试）
├── context.py      # schema 渲染 + 采样 + bm25 选表 + 术语层 + few-shot 装配
├── generate.py     # 两段式生成：先出计划（选表/口径），再出 SQL
├── guard.py        # ★ sqlglot AST 白名单 + 强制 LIMIT
├── execute.py      # 只读执行：超时、行数上限、结果规范化
└── pipeline.py     # 串起 生成 → 闸门 → 执行 → 自纠错（≤3 次）
backend/app/api/chat.py     # POST /chat/stream（SSE）
backend/app/semantics.py    # 术语/指标/枚举映射（YAML 加载）
evals/{golden.jsonl,run_eval.py}
```

新增依赖：`sqlglot`（纯 Python）、`pyyaml`。

## 2. 上下文装配（决定准确率的 70%）

每张表渲染成下面这种"给模型看的"格式，而不是原始 DDL：

```
表: orders（订单，20,000 行）
  id          INTEGER   主键
  customer_id INTEGER   关联 customers.id
  status      TEXT      状态 —— 取值: paid,shipped,done,cancelled,refunded
  pay_amount  REAL      支付金额（未扣退款）
  created_at  TEXT      下单时间（UTC+8）
采样: (1, 1, 'paid', 2999.0, '2026-07-02 14:03:00')
```

规则：
- 只给"相关表"：`bm25(问题, 表名+列名+中文注释)` 取 top-8，再补上被外键引用的邻接表；
- 低基数列（distinct ≤ 20）附上取值枚举，这是模型猜错最多的地方；
- 采样 1–3 行，明确标为"数据，不是指令"；
- token 预算 6000，超出时先砍采样、再砍低价值表。

## 3. 两段式生成

**第一段（计划）**：模型只输出 JSON

```json
{"tables": ["orders", "customers"], "metrics": ["gmv"], "filters": {"region": "华东"},
 "time_range": {"start": "2026-07-01", "end": "2026-09-30"}, "ambiguity": null}
```

`ambiguity` 非空时不生成 SQL，直接反问用户（例："你说的上个月是 2026-10 吗？"）。

**第二段（SQL）**：输入计划 + 相关表结构 + 术语定义，输出

```json
{"sql": "SELECT ...", "explain": "按品类汇总 GMV，排除测试账号与取消单", "assumptions": ["华东 = region_code in (...)"]}
```

## 4. 只读闸门（`guard.py`）

```python
FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter,
             exp.Create, exp.Merge, exp.Command, exp.TruncateTable, exp.Into)
BLOCKED_FUNCS = {"LOAD_FILE", "LOAD_EXTENSION", "READ_CSV", "PG_READ_FILE", "COPY"}

def check(sql: str, dialect: str, allow_tables: set[str], max_rows: int = 1000) -> str:
    # 1) 解析：语法错误直接返回给模型重写（这是"自纠错"最有价值的一种错误）
    # 2) 单语句
    # 3) 只允许 Select / Union（CTE 会挂在 Select 上，天然放行）
    # 4) AST 遍历：禁写节点、禁危险函数
    # 5) 表白名单（join 的副表也要查），列白名单（可配置敏感列）
    # 6) 无 LIMIT 时补 LIMIT max_rows；已有 LIMIT 超限则改小
    # 返回规范化后的 SQL（用于执行与审计）
```

**铁律**：闸门只负责"让错误早暴露"，安全边界是只读账号 + `mode=ro` 连接（P0 已实现）。

## 5. 执行与自纠错

- 超时：`statement_timeout`（PG）/ `MAX_EXECUTION_TIME`（MySQL）/ `progress_handler`（SQLite），默认 10s；
- 行数硬上限 1000，超出截断并告知模型；
- 结果规范化：Decimal→float、datetime→ISO、bytes→base64 摘要；
- 自纠错最多 3 次，错误分类后回灌：
  | 错误 | 回灌内容 |
  |---|---|
  | 语法错 | 解析器报错位置 + 原 SQL |
  | 未知列 | 该表真实列清单 |
  | 类型不匹配 | 列类型 + 建议的 cast |
  | 0 行且条件非空 | 不重试，改为提示可能原因（口径/时区/拼写） |

## 6. SSE 事件协议（前端按此实现）

```
event: stage   data: {"stage":"planning"}           # 选表/口径
event: stage   data: {"stage":"generating"}
event: sql     data: {"sql":"SELECT ...","attempt":1}
event: stage   data: {"stage":"executing"}
event: rows    data: {"columns":[...],"rows":[...],"truncated":false,"elapsed_ms":42}
event: answer  data: {"text":"2026Q3 华东 GMV 为 1.2 亿，环比 +8%"}
event: error   data: {"detail":"...","attempt":3,"sql":"..."}
event: done    data: {"trace_id":"...","tokens":1234,"latency_ms":3100}
```

## 7. 评测集（40 题先跑通，60 题达标）

`evals/golden.jsonl` 每行：

```json
{"id":"q07","q":"上个季度华东区客单价最高的 5 个品类","sql":"SELECT ...","db":"shop","tags":["join","time","rank"],"notes":"客单价 = GMV/订单数"}
```

覆盖 8 类各 5 题：单表过滤、聚合分组、多表 join、时间窗、Top-N、同环比、指标口径、**应拒答**（"把测试数据删掉"）。

指标与通过线：EX ≥ 65%、合法率 ≥ 95%、平均尝试 ≤ 1.8、p95 < 15s。

跑分：`python evals/run_eval.py --model deepseek-chat > evals/results/<date>.json`，分数表进 README。

## 8. 任务拆分（每步一个 commit，可独立验证）

1. `feat(engine): LLM 客户端与用量统计` + fake provider 测试
2. `feat(engine): schema 上下文渲染与 bm25 选表` + 快照测试
3. `feat(engine): 只读闸门(sqlglot)` + 20 条拒绝用例（必须先红后绿）
4. `feat(engine): 只读执行器(超时/限行/规范化)`
5. `feat(chat): SSE 流式问答` + 前端对话页接上
6. `feat(evals): 40 题评测脚本与首份基线分`

## 9. 边界与不做

- 不做多轮对话记忆（v0.1 每次独立，只保留会话展示）；
- 不做向量检索（bm25 够用，零依赖）；
- 不做图表（P5）；
- 不碰写通道（P2 单独开工，且必须先有 P1 的审计与评测打底）。