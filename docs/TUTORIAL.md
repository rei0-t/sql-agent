# 从零读懂一个 SQL Agent

> 这份文档写给**第一次接触 agent 的人**。读完你应该能回答三个问题：
> 一次提问在代码里到底走了哪几步？为什么要拆成这几步？我改哪里能让它变好？
>
> 全部内容基于这个仓库的真实实现，不是通用理论。每条结论都能在代码里找到对应位置。

---

## 怎么用这份文档

| 你的目标 | 读哪几章 | 时间 |
|---|---|---|
| 只想搞懂它怎么跑的 | 第 1、2 章 | 40 分钟 |
| 要动手改它 | 第 1–3 章 + 第 6 章实验 | 2 小时 |
| 要做类似产品 | 全部 + 第 8 章 | 半天 |

前置要求很低：会一点 Python、会写 `SELECT` 就行。不需要懂深度学习，也不需要懂 agent 框架——**这个项目一个 agent 框架都没用**。

---

## 第 1 章 先破除四个误解

### 误解一：这是个"自主 agent"

不是。自主 agent（ReAct、AutoGPT 那类）是「模型自己决定下一步做什么、调用哪个工具、什么时候停」。这个项目是**固定流水线**：五步写死在 `pipeline.py` 里，模型只在三个固定位置被调用，没有工具调用循环，没有"模型决定下一步"。

```
用户问题
   │
   ├─① 装配上下文        build_context()       ← 查库结构（不走模型）
   ├─② 出分析计划        make_plan()           ← 模型调用 1
   ├─③ 写 SQL            write_sql()           ← 模型调用 2
   ├─④ 校验 + 执行       check() / run_select() ← 不走模型
   └─⑤ 写一句话结论      summarize()           ← 模型调用 3
```

**为什么 SQL 场景不选自主 agent？** 三个理由，都很实在：

1. **可测**。固定流水线可以给每一步写单测；自主 agent 的行为空间是发散的，测试只能覆盖"见过的路径"。
2. **可归因**。答错了，你能确定是选错表、口径错、SQL 语法错、还是结论写错——因为每一步的输入输出都留下了。自主 agent 只有一段思考链，出错只能靠猜。
3. **可控成本**。固定 3 次调用，token 可预估；自主 agent 的调用次数取决于模型心情。

> 这不是说自主 agent 没用，而是说：**任务边界清晰、对正确性要求高的场景，脚手架（scaffolding）比自主性更值钱。**
> 真实的 agent 产品大多是这两种的混合——固定骨架 + 局部自主。

### 误解二：模型在执行 SQL

不是。模型只输出**文本**，真正的执行发生在 Python 里：

```
模型产出文本 → extract_json() 解析 → check() 校验 → run_select() 执行
                                    ↑ 校验不通过，SQL 根本没机会碰数据库
```

而且连接本身就是只读的：SQLite 用 `mode=ro`，MySQL/PG 要求你用只读账号。这是两道独立的门：

| 门 | 位置 | 作用 |
|---|---|---|
| 闸门（软） | `engine/guard.py` | 让错误尽早暴露，把 SQL 规范化 |
| 权限（硬） | `dialects.py` + 数据库账号 | 真正的安全边界：即使闸门有洞，也写不进去 |

`guard.py` 开头那句注释值得背下来：

> 闸门负责让错误尽早暴露，**真正的安全边界是只读账号与只读连接**。

### 误解三：准确率靠更强的模型

不是。这个项目 20 题评测做到 95%，用的 `qwen-plus`——不是最强的模型。真正起作用的是三件事：

1. **上下文**：只给模型看相关的那几张表（BM25 选表），列名带中文注释，每张表给 3 行真实采样，再拼上业务口径。
2. **两段式**：先让模型说清"用哪些表、什么口径、什么时间范围"，再让它写 SQL。
3. **闭环**：写错了会被校验/数据库拒绝，错误分类后回灌，最多重写 3 次。

换句话说：**把模型当成一个口语很好但会犯低级错误的 SQL 实习生**，你的工作是给他准备好资料、检查他的输出、告诉他错在哪。

### 误解四：模型直接吐 SQL

不是——它吐的是 JSON：

```json
{"sql": "SELECT ...", "explain": "一句话说明在算什么", "assumptions": ["做过的假设"]}
```

**为什么要包一层 JSON？** 因为纯文本 SQL 没法附带元信息：你拿不到"这条 SQL 假设了什么"，前端没法显示"这条 SQL 在算什么"，日志里也只剩下一坨字符串。代价是解析可能失败——模型爱把 JSON 包进代码块，或者前后加一句"好的，这是你要的 SQL"，所以有个 `extract_json()` 专门负责剥壳。

---

## 第 2 章 一次提问的完整旅程

这是全文最重要的一章。跟着一条真实的提问走一遍，你就掌握了 80%。

### 2.1 时序

```
浏览器              FastAPI                pipeline.py          数据库 / 大模型
  │  POST /chat/stream  │                      │                     │
  │────────────────────>│  chat_stream()       │                     │
  │                     │  ├ 校验数据源归属     │                     │
  │                     │  ├ 解密口令           │                     │
  │                     │  └ 起一个 worker 任务 │                     │
  │<── event: stage ────┤                      │                     │
  │                     │  answer_question() ─>│                     │
  │                     │                      ├ build_context() ───>│ 读表结构 + 采样
  │<── event: stage ────┤                      ├ make_plan() ───────>│ 模型调用 1
  │<── event: stage ────┤                      ├ write_sql() ───────>│ 模型调用 2
  │                     │                      ├ check()  本地 sqlglot│
  │<── event: sql ──────┤                      ├ run_select() ──────>│ 执行 SQL
  │<── event: rows ─────┤                      ├ summarize() ───────>│ 模型调用 3
  │<── event: answer ───┤                      └ 写审计              │
  │<── event: done ─────┤                      │                     │
```

### 2.2 线上的真实帧（用第 6 章实验 2 可以自己抓）

```
event: stage
data: {"stage": "context"}

event: stage
data: {"stage": "planning"}

event: stage
data: {"stage": "generating", "attempt": 1}

event: sql
data: {"sql": "SELECT SUM(o.pay_amount) AS gmv FROM orders AS o JOIN customers AS c ON c.id = o.customer_id WHERE ... LIMIT 200", "attempt": 1, "explain": "按季度与大区聚合成交额"}

event: stage
data: {"stage": "executing", "attempt": 1}

event: rows
data: {"columns": ["gmv"], "rows": [[15579548.46]], "truncated": false, "elapsed_ms": 12}

event: stage
data: {"stage": "summarizing"}

event: answer
data: {"text": "2026 年第三季度华东区的 GMV 是 15579548.46。", "attempts": 1, "elapsed_ms": 11783, "tokens": 5042}

event: done
data: {"ok": true, "attempts": 1, "elapsed_ms": 11783, "tokens": 5042, "model": "qwen-plus", "error": null, "clarification": null}
```

七种事件，各有各的用途：

| 事件 | 什么时候发 | 前端拿它干什么 |
|---|---|---|
| `stage` | 每进入一个阶段 | 显示"正在读表结构 / 正在写 SQL" |
| `sql` | 校验通过、即将执行 | 先把 SQL 亮出来（此时还没执行） |
| `rows` | 执行完 | 渲染结果表 |
| `answer` | 结论生成完 | 显示那句话 + token/耗时 |
| `clarify` | 信息不足，需要反问 | 显示问题，不显示 SQL |
| `error` | 某次尝试失败 | 显示错误码（还会继续重试） |
| `done` | 一定发（含异常兜底） | 收尾、解除 loading |

注意 `error` 是**非终态**：一次尝试失败不结束，`done` 才是终点。

### 2.3 每一步落在哪个文件

| 阶段 | 函数 | 文件 | 关键点 |
|---|---|---|---|
| 建流 | `chat_stream` | `api/chat.py` | queue + worker，生成与发送解耦 |
| 装配 | `build_context` | `engine/context.py` | BM25 选表 + 采样 3 行 + 语义层 |
| 计划 | `make_plan` | `engine/generate.py` | 只输出 JSON，不写 SQL |
| 写 SQL | `write_sql` | `engine/generate.py` | 带 `feedback` 参数 → 这是自纠错的入口 |
| 校验 | `check` | `engine/guard.py` | sqlglot AST 检查 + 强制 LIMIT |
| 执行 | `run_select` | `engine/execute.py` | 超时、行数上限、类型 JSON 化 |
| 循环 | `answer_question` | `engine/pipeline.py` | 最多 3 次，错误分类后重写 |
| 结论 | `summarize` | `engine/generate.py` | 只看前 20 行，禁止心算 |

耗时分布：**大头在三次模型调用**（合计 10 秒上下），SQL 执行通常只有几十毫秒。所以优化性能的第一顺位不是数据库，是"少调一次模型"或"换更快的模型"。

---

## 第 3 章 六个模块逐个拆

### 3.1 context.py：给模型看什么，比怎么问更重要

很多人以为 prompt 措辞决定成败。实际上**塞进去什么**才是主因。

跑一下 `scripts/inspect_context.py`（第 6 章实验 1），你会看到模型真实收到的：

```
## 可用的表（共 5 张，已按问题相关性筛选）

表 orders（约 20,000 行）
  id INTEGER   PK
  customer_id INTEGER   NOT NULL
  status TEXT   NOT NULL
  pay_amount REAL   NOT NULL
  created_at TEXT   NOT NULL
  采样: (1, 831, 'shipped', 6171.04, '2026-02-28 17:42:00'), ...

## 业务口径
指标定义（必须使用这里的算式与过滤条件）：
- GMV（gmv）= SUM(orders.pay_amount)
    必须附加：orders.status IN ('paid','shipped','done')
    ...
```

四件事值得注意：

**① 只给相关表。** `rank_tables()` 用 BM25 从全库选前 8 张（`schema_max_tables`）。为什么不倒整个库？因为表一多，模型的注意力会被稀释，而且 token 成本线性上涨。

**② 中文按二元组切词。** `_tokenize()` 没有引入分词库：英文按词、中文按相邻两字（"华东区" → 华东、东区）。够用，且零依赖。BM25 参数是经典的 `k1=1.4, b=0.75`。

**③ 外键补齐。** 光靠 BM25 会漏关联表：问题只问"华东区 GMV"，可能只选中 `orders`，但 `region` 在 `customers` 上。所以选完 Top-K 后还有一轮扫尾——如果某表的列名是 `xxx_id` 且 `xxx` 在已选表里，就把它也带上。

**④ 采样 3 行。** 这一条经常被忽略但极其关键：

```
status TEXT   ← 模型不知道里面存的是 'paid' 还是 1
采样: (1, 831, 'shipped', 6171.04, ...)   ← 看一眼就知道了
```

没有采样，模型会猜枚举值的写法；有了采样，它知道是英文小写字符串、时间格式是 `'2026-02-28 17:42:00'`。

缓存：结构快照缓存 60 秒（`schema_cache_ttl`），键是 `数据源 id:类型:库名:主机:端口`。

### 3.2 generate.py：为什么要分两步问

一次直出 SQL，模型要同时决定：选哪些表、用什么口径、怎么过滤、语法怎么写。四件事混在一个动作里，错了你不知道错在哪。

两段式把它拆开：

| | 第一步 `make_plan` | 第二步 `write_sql` |
|---|---|---|
| 输出 | `{"tables", "metrics", "filters", "time_range", "clarification"}` | `{"sql", "explain", "assumptions"}` |
| max_tokens | 500 | 800 |
| 失败后果 | 反问用户 | 进入重写循环 |

Plan 阶段的 prompt 有三条容易被忽略但很重要的规则：

- **"信息不足才反问，能用默认口径回答的不要反问"**。过度反问比答错更烦人。
- **"问题没提时间范围时，默认统计全部历史"**。这是产品的默认行为，不是遗漏。
- **"不要在这步写 SQL"**。不写这句，模型会忍不住把 SQL 一起写出来，两段式就退化了。

第二步的 `write_sql()` 有一个 `feedback` 参数——**这是整个自纠错机制的物理接口**：

```python
parts = [f"## 用户问题\n{question}", f"## 分析计划\n{plan.render()}", context_text]
if feedback:
    parts.append(f"## 上一次失败的原因（必须修正）\n{feedback}")
```

重写时不是把历史消息全传回去（那样 token 会滚雪球），而是把**上一次的错误压缩成一行**再发一次。这是个工程取舍：省 token，但会丢掉"上一条 SQL 长什么样"的信息。

第三步 `summarize()` 的 prompt 里有一句硬规矩：

> 用一句中文回答用户的问题，必须包含关键数字，**不要解释 SQL，不要罗列过程**。

以及格式规则："计数用整数（1565，不要 1565.00），金额与比例保留两位小数"。模型很擅长把 1565 写成 1565.00，所以规则要写死。

### 3.3 guard.py：只读闸门

`check()` 干四件事，任何一件不过就抛 `GuardError`：

```
① 解析      sqlglot.parse(sql, read=dialect)         → 语法错误直接拒
② 语句类型  必须是单条 SELECT / UNION                  → INSERT/UPDATE 全拒
③ 内容检查  遍历 AST：禁用节点（Drop/Alter/...）+ 禁用函数（LOAD_FILE/SLEEP/...）
④ 表白名单  实际引用的表必须 ⊆ 候选表（CTE 名不算）    → 防止越权读别的表
⑤ 强制 LIMIT 没有就补、太大就改小、非字面量就包一层
```

第 ⑤ 步的三种情况值得单独看，因为它是"从严格到更严格"的递进：

```python
if current is None:                    # 没有 LIMIT
    return stmt.limit(max_rows)
if isinstance(expression, exp.Literal): # LIMIT 10000 → LIMIT 200
    ...
return exp.select("*").from_(stmt.subquery("_bounded")).limit(max_rows)  # LIMIT ? → 外面包一层
```

最后那种情况（LIMIT 是参数或表达式）最容易被忽略：你没法静态判断它会不会返回一千万行，那就**在外面再套一层 LIMIT**——反正结果集一样，但行数受控。

错误码一共 7 个：`empty`、`syntax`、`multiple_statements`、`not_select`、`forbidden_statement`、`forbidden_function`、`table_not_allowed`。每个码都会变成 `[code] 说明` 回灌给模型——**错误码本身就是 prompt**，模型看到 `table_not_allowed` 就知道该换表。

### 3.4 execute.py：执行器

三处资源保护，缺一不可：

```python
await _apply_timeout(conn, ds.type, timeout)      # ① 数据库侧：PG 的 statement_timeout
result = await asyncio.wait_for(_run(), timeout=timeout + 2)   # ② 进程侧：兜底 +2 秒
fetched = result.fetchmany(max_rows + 1)          # ③ 多取 1 行，用来判断 truncated
```

**为什么多取 1 行？** 取 200 行分不清"正好 200 行"和"有 1 万行"。取 201 行再截断，就能准确告诉用户"结果被截断了"。

**为什么超时 +2 秒？** 数据库侧的 `statement_timeout` 先触发，会返回一个正常的错误（能归类、能回灌给模型）；进程侧的 `wait_for` 是防数据库不听话的兜底。

`jsonable()` 把驱动返回的类型转成 JSON 安全的值：`Decimal → float`、`datetime → isoformat`、大 `bytes → "<N bytes>"`（不把二进制塞进响应里）。

`_classify()` 把驱动异常翻译成四个可操作的类型：

| 原始报错含 | 归类 | 回灌给模型后模型会做什么 |
|---|---|---|
| `no such column` / `unknown column` | `unknown_column` | 换列名 |
| `no such table` | `unknown_table` | 换表 |
| `syntax` | `syntax` | 修语法 |
| `ambiguous` | `ambiguous` | 加表别名 |
| 其它 | `execution` | 缩小范围 / 换写法 |

### 3.5 pipeline.py：主循环

`answer_question()` 是唯一的编排点。核心是这个循环：

```python
for attempt in range(1, settings.max_repair + 1):     # 默认 3 次
    draft = await write_sql(..., feedback=feedback)    # 带上次的错误
    guarded = check(draft.sql, ...)                    # 校验
    result = await run_select(...)                     # 执行
    break                                              # 成功才 break
```

每次失败分两条路：

- `GuardError` / `ExecutionError` → `feedback = exc.to_model_feedback()`，继续下一次
- 模型自己抽风（`LLMError`，比如没吐 JSON）→ `feedback = "[llm] ... 请只输出合法 JSON"`，继续

三次都失败，`answer.error` 就是最后一次的 feedback——所以前端看到的错误是**最后一次尝试的原因**，不是第一次的。

还有一个容易被忽略的早退分支：plan 阶段返回了 `clarification` 就直接返回，**不写 SQL、不执行**。这是"宁可问一句，不要瞎猜"的落地。

### 3.6 chat.py：SSE 的工程细节

这段代码不长，但每处都有原因：

**① 为什么用 queue + 独立 task？**

```python
queue = asyncio.Queue()
async def worker(): ...          # 干活，往 queue 里塞字符串
task = asyncio.create_task(worker())
async def event_source(): ...    # 从 queue 里取，yield 给客户端
```

如果不解耦，`yield` 会卡在正在执行的协程里——生成 SQL 的 10 秒内一个字节都发不出去。用了 queue，**"生成"和"发送"两条时间线才能并行**：模型thinking 的时候，前端已经能看到"正在写 SQL"。

**② 为什么 `_snapshot()` 复制一份 Datasource？**

`StreamingResponse` 返回后，请求级的 `AsyncSession` 就关了。如果流式过程中还持有 ORM 对象并触发懒加载，会报 `DetachedInstanceError`。复制一个脱离会话的普通对象最省事。

**③ 为什么加 `X-Accel-Buffering: no`？**

这是给 Nginx 看的：告诉它别缓冲这个响应。少了这个头，Nginx 会攒够一个 buffer 才转发，前端就会"卡住 10 秒然后一次性刷出来"——这正是我们部署文档里反复强调 SSE 要关缓冲的原因。

**④ 为什么审计在 `finally` 里？**

因为**失败的请求最需要审计**。用户报"它答错了"，你得能看到那条问题、那条 SQL、那个错误码。

---

## 第 4 章 三个"看起来多余"的设计

### 4.1 语义层 YAML：把业务口径从 prompt 里挪出来

`backend/data/semantics.yaml` 有四段：`metrics`（指标口径）、`synonyms`（同义词）、`notes`（约定）、`examples`（示例 SQL）。

```yaml
metrics:
  gmv:
    name: GMV
    expr: SUM(orders.pay_amount)
    filters:
      - orders.status IN ('paid', 'shipped', 'done')
    note: 排除测试账号 c.is_test = 1
```

**为什么不用 prompt 硬编码？** 三个理由：

1. **口径是业务资产，不是代码**。运营改口径不该让工程师改代码发版。
2. **可以按库定制**。换一个客户、换一套表结构，只换 YAML。
3. **可被编辑坏**。写错了能看到、能 diff、能回滚——藏在 prompt 字符串里的规则做不到。

`examples` 是性价比最高的一段：给两三条"问题 + 正确 SQL"，模型会照着模仿。这和 RAG 里的 few-shot 是一个思路。

### 4.2 temperature=0 + seed：为了可复现

```python
llm_temperature: float = 0.0
llm_seed: int | None = None   # 项目里设成 42
```

温度 0 让输出尽量确定；`seed` 是给支持采样的服务端一个固定种子。两者加起来意味着：**同样的输入，大概率得到同样的输出**。

为什么这么在意复现？因为你要做评测：改了 prompt，跑 20 题，EX 从 95% 掉到 80%，你得能确定这个变化是 prompt 引起的，不是模型今天心情不好。不可复现的系统，也就不可优化。

### 4.3 强制 LIMIT：保护数据库，代价是"总数"要另算

`read_max_rows=200`。所有查询都会被加/改 LIMIT 200。好处是任何一条 SQL 都不可能把生产的表拖垮。

代价：用户问"一共有多少订单"，如果模型写 `SELECT * FROM orders`，你只能拿到 200 行，得不出真实总数。所以正确的做法是让模型写 `COUNT(*)`——语义层里的 `notes` 就在强调这件事。

> `execute.py` 里还留着一个 `count_rows()`：包一层 `SELECT COUNT(*) FROM (...)`。它现在**没有被任何代码调用**，是为 P2 变更通道准备的——将来要告诉用户"这条 UPDATE 会影响多少行"，就得靠它。这是"读代码时看到死代码，先查清楚它为什么在那儿"的例子。

---

## 第 5 章 怎么证明它是对的

### 5.1 评测集长什么样

`evals/golden.jsonl`，每行一题：

```json
{"id": "q3", "question": "2026 年第三季度华东区的 GMV 是多少", "sql": "SELECT ...", "tolerance": 1e-6}
```

### 5.2 为什么比结果集，不比 SQL 文本

同一条业务问题有无数种正确写法（`JOIN` vs 子查询、列顺序、别名、`>=` 加 `<` vs `BETWEEN`）。比文本会把"写法不同但答案正确"判成错。

所以 `run_eval.py` 的做法是：**分别执行标准 SQL 和模型 SQL，比较结果集**——列数、行数、每行内容（数值容差 1e-6），排序和别名不算差异。

这是一个很重要的方法论：**评测要贴着"用户关心的东西"设计**。用户关心数字对不对，不关心你写没写 `AS`。

### 5.3 评测集里故意埋的陷阱

演示库 `scripts/seed_demo.py` 生成了 2 万笔订单，其中：

- 5% 的客户是**测试账号**（`is_test=1`）
- 8% 的订单**已取消/退款**
- 退款金额在**单独的表** `refunds` 里

于是"GMV"这道题有了分水岭：

| 写法 | 结果 | 判定 |
|---|---|---|
| `SUM(pay_amount)` | 比真值高约 16% | ❌ |
| 加 `status IN ('paid','shipped','done') AND is_test=0` | `15,579,548.46` | ✅ |

**16% 的差距，肉眼看不出来**——这就是为什么必须自动化评测，也是为什么语义层里的 `filters` 那么重要。

### 5.4 一个真实的失败案例：fan-out 双算

最早一版评测里，"各品类 GMV 排名"这道题**三次跑两次错**：算出来 2.21 亿，真值 1.33 亿。

原因：SQL `JOIN order_items` 之后，一行订单变成多行明细，再对订单级的 `pay_amount` 求和就被重复累加了几次。这是数据仓库里经典的 **fan-out（扇出）** 问题。

修法不是改模型，是改规则：写进 `write_system` 的硬性要求——

> 一张订单可能有多条明细：按商品/品类统计金额时只能用 `order_items` 的 `quantity * unit_price`，不要对订单级金额做 SUM。

同时语义层加了 `gmv_by_category` 指标（从 `order_items` 起算）。**改完就稳定了**。

### 5.5 一个"故意失败"的题

20 题里唯一没通过的是 q17「测试账号贡献的 GMV 是多少」：模型指出"这和 GMV 口径（必须排除测试账号）自相矛盾"，于是反问而不是硬算。

评测按"没给出结果"记为失败，**我们没改判定规则去迁就它**。因为这种追问恰恰是想要的行为——评测规则严格一点，模型才有压力。

### 5.6 怎么跑

```bash
cd backend
python ../evals/run_eval.py            # 直接跑
python ../evals/run_eval.py --save     # 结果存到 evals/results/
```

> ⚠️ 20 题全部基于**同一个演示库**，属于过拟合的评测集。真实项目要按客户自己的库重建评测集，这是最重要的一步准备工作。

---

## 第 6 章 动手实验

六个实验，都能在本地独立完成，不需要大模型的有 3 个（不花钱）。

### 实验 1：看模型到底收到什么（不花钱）

```bash
cd backend
python ../scripts/inspect_context.py --sqlite ../data/demo/shop.db --question "2026 年第三季度华东区的 GMV 是多少"
```

**预期**：打印出 5 张表、每张表的列与采样、业务口径、示例 SQL，最后一行是字符数（约 3900 字符）。

**想一想**：
- 把问题改成「退款率是多少」，选中的表会变吗？（提示：看 BM25 的打分）
- 把 `--limit 2` 传进去，只给两张表，上下文会漏掉什么？
- 如果库里只有 3 张表（少于 `schema_max_tables`），`rank_tables` 会怎么做？（读代码：`if len(tables) <= top_k: return tables`）

### 实验 2：用 curl 抓 SSE 逐帧（不花钱，但需要配好模型）

先去设置页配好 Key，然后：

```bash
# 取 token
curl -s http://127.0.0.1:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"你的密码"}'

# 用返回的 access_token
curl -N -s http://127.0.0.1:8080/api/v1/chat/stream \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"datasource_id":1,"question":"2026 年第三季度华东区的 GMV 是多少"}'
```

`-N` 是关键：关掉 curl 自己的缓冲，你才能看到帧一个个冒出来。

**预期**：先出 `stage: context`，几秒后 `stage: planning`、`generating`，然后 `sql`、`rows`、`answer`、`done`。

**想一想**：哪一帧之间间隔最长？（那就是模型的耗时所在，通常 `planning → generating` 和 `summarizing`）

### 实验 3：让闸门拒绝一条 SQL（不花钱）

不用起服务、不用连库，仓库里带了个演示脚本：

```bash
cd backend
python ../scripts/guard_demo.py
```

**预期输出**（9 个用例，放行 4 条、拦下 5 条）：

```
允许访问的表：customers, orders

✅ 最普通的查询
   输入: SELECT 1
   放行: SELECT 1 LIMIT 200

⛔ 写操作
   输入: DELETE FROM orders
   原因: [not_select] 只允许 SELECT 查询，收到 Delete

⛔ 子查询里的越权
   输入: SELECT * FROM orders WHERE id IN (SELECT id FROM secret_table)
   原因: [table_not_allowed] 引用了未授权的表：secret_table
...
小结：放行 4 条，拦下 5 条
```

三个值得停下来看的点：

1. **`SELECT * FROM orders LIMIT 999999` 被改成了 `LIMIT 200`**，不是拒绝——闸门的目标是"能安全执行"，不是"挑刺"。
2. **CTE 不会被误判**：`WITH t AS (...) SELECT * FROM t` 放行。`_cte_names()` 把临时表名从"已用表"里减掉了。
3. **子查询里的越权也能抓到**：`WHERE id IN (SELECT id FROM secret_table)` 被拒。因为检查是遍历整棵 AST，不是只看最外层。

**想一想**：`LIMIT ?`（参数化）会被怎么处理？（读 `_enforce_limit()` 最后那条分支——外面再包一层 `SELECT * FROM (...) LIMIT 200`）

### 实验 4：加一个指标，看回答怎么变（需要模型）

1. 打开 `backend/data/semantics.yaml`，加一段：

```yaml
metrics:
  avg_order_value:
    name: 客单价
    expr: SUM(orders.pay_amount) / COUNT(DISTINCT orders.id)
    filters:
      - orders.status IN ('paid', 'shipped', 'done')
```

2. 重启服务（YAML 是每次请求读的，其实不用重启——试着验证这句话）
3. 问：「客单价是多少」
4. 再用实验 1 的脚本看上下文，确认新指标进去了

**预期**：不加指标时，模型会自己编一个口径（可能除的是订单数也可能除的是客户数）；加了之后稳定用你的定义。

**想一想**：如果 YAML 写错缩进，会发生什么？（读 `load_semantics()` 的 `except yaml.YAMLError: return Semantics()`——**静默失败**。这是个可以改进的点：至少应该打日志。）

### 实验 5：用 FakeModel 写零成本测试（不花钱）

这是本项目测试的核心技巧：**不让测试碰真模型**。

```python
# backend/tests/test_my_experiment.py
import json
from app.engine.llm import FakeModel
from app.main import app

def test_my_case(client, sqlite_datasource):
    plan = json.dumps({"tables": ["orders"], "metrics": [], "filters": [],
                       "time_range": "", "clarification": ""})
    sql = json.dumps({"sql": "SELECT COUNT(*) AS n FROM orders", "explain": "", "assumptions": []})
    app.state.llm = FakeModel([plan, sql, "共有 2 笔订单。"])
    try:
        r = client.post("/api/v1/chat/stream", headers=admin_headers,
                        json={"datasource_id": sqlite_datasource["id"], "question": "多少订单"})
        assert "event: answer" in r.text
    finally:
        app.state.llm = None
```

**为什么这样写？** `deps.get_model()` 会优先返回 `app.state.llm`。这是**依赖注入 + 测试替身**的标准做法：测试跑得快、不花钱、结果稳定。

**想一想**：`FakeModel.responses` 是按顺序消费的。如果第一轮被闸门拒绝、进入第二次尝试，你需要准备几条响应？（提示：每次都消耗一条）

### 实验 6：改 prompt，复跑评测（需要模型，约 10 分钟）

1. 在 `generate.py` 的 `WRITE_SYSTEM_TEMPLATE` 里加一条规则，比如：

```
- 结果只有一行一列时，不要加 ORDER BY
```

2. 跑评测：`python ../evals/run_eval.py --save`
3. 看 EX 变化，以及哪几题变了

**预期**：可能不变，也可能掉一两题。**这很正常**——prompt 改动经常是"修好一个、弄坏另一个"。

**想一想**：如果 EX 掉了，你怎么判断是这条规则的问题，还是随机性？（答案：`seed=42` + 多跑两次对比）

---

## 第 7 章 出问题怎么查

### 7.1 按症状定位

| 症状 | 先看哪里 | 大概率原因 |
|---|---|---|
| 前端一直转圈，没有任何 stage | 网络层 / 反代 | SSE 被缓冲了（Nginx 少了 `proxy_buffering off`） |
| 停在 `context` 不动 | `build_context` | 数据源连不上、口令错、库名错 |
| 停在 `planning` | 模型配置 | Key 无效 / Base URL 错 / 超时 |
| 反复 `error` 后 `done` 失败 | 错误码 | 见 7.2 |
| SQL 对但结论错 | `summarize` | 模型心算了（本次是让它只看前 20 行） |
| 数字差一个数量级 | 口径 | 语义层没配，或者 `notes` 没写清 |
| 数字差 16% 左右 | fan-out | 订单级金额被明细行重复累加 |

### 7.2 错误码速查

| code | 来源 | 模型应该怎么改 | 你该做什么 |
|---|---|---|---|
| `empty` | guard | 输出 SQL | 看模型是不是在胡说 |
| `syntax` | guard | 修语法 | 检查方言配置 |
| `multiple_statements` | guard | 只写一条 | — |
| `not_select` | guard | 改成 SELECT | — |
| `forbidden_statement` | guard | 去掉写操作 | 如果是正常需求，说明该开 P2 |
| `forbidden_function` | guard | 换函数 | 检查是否真需要该函数 |
| `table_not_allowed` | guard | 换表 | 检查 BM25 是不是漏选了表 |
| `unknown_column` | execute | 换列名 | 检查列注释是否缺失 |
| `unknown_table` | execute | 换表 | 检查 schema 快照是否过期（60 秒缓存） |
| `ambiguous` | execute | 加别名 | — |
| `timeout` | execute | 加过滤条件 | 检查索引 / 调大 `query_timeout` |

### 7.3 审计表是你最好的朋友

每次问答都会写一条 `chat.read`：

```sql
SELECT created_at, actor_name, json_extract(detail,'$.question') AS q,
       json_extract(detail,'$.attempts') AS tries,
       json_extract(detail,'$.error') AS err,
       json_extract(detail,'$.tokens') AS tokens
FROM audit_logs WHERE action='chat.read' ORDER BY id DESC LIMIT 20;
```

（PostgreSQL 用 `detail->>'question'`。）

**看什么**：`attempts > 1` 的题目就是模型的弱点，`error` 非空的直接就是失败样本。把这些攒起来，就是你的下一版评测集。

---

## 第 8 章 从这里往哪走

### 8.1 概念补课（按优先级）

| 概念 | 为什么重要 | 在本项目里的影子 |
|---|---|---|
| **Prompt 工程** | 决定模型输出格式与约束 | `generate.py` 的三个 SYSTEM |
| **Function calling / Tool use** | 自主 agent 的基础 | 本项目**故意没用**，但你要知道它是什么 |
| **RAG** | 上下文检索的通用范式 | BM25 选表就是最朴素的 RAG |
| **评测（Eval）** | 没有评测就没有优化 | `evals/` |
| **Guardrails** | 生产环境的护栏 | `guard.py` |
| **可观测性** | 出问题能查 | SSE stage + 审计 |

### 8.2 三个进阶改造（从易到难）

**A. 结果缓存（半天）**

同一个数据源 + 同一个问题，短时间内重复问，可以直接返回上次结果。

- 改动点：`chat_stream` 前加一层 `dict[(ds_id, question_hash)] → (answer, timestamp)`
- 坑：数据变了要能失效；要和 `schema_cache_ttl` 对齐

**B. 列级检索（1–2 天）**

现在 BM25 是按"表"打分，表多的时候会选错。改成按列打分再聚合到表，能显著提升大库的选表准确率。

- 改动点：`_document()` 从"整表一个文档"变成"每列一个文档"，得分按表求和
- 验证：造一个 50 张表的库，看 Top-8 命中率

**C. 变更通道（P2，1–2 周）**

这是这个项目故意没做的部分，也是最能体现"agent 做危险操作"设计难度的部分。核心不是生成 UPDATE，而是：

1. **dry-run**：先 `EXPLAIN` 或包在事务里执行再回滚，告诉用户会影响多少行
2. **diff 预览**：把"改前 → 改后"展示出来让人确认
3. **回执**：执行后记录影响行数、耗时、可回滚的反向 SQL
4. **权限分级**：读 L0 / 写 L2，写操作强制独立账号

`execute.py` 里那个没被调用的 `count_rows()` 就是为第 1 步准备的。

### 8.3 读代码的顺序建议

```
config.py → models.py → engine/pipeline.py → engine/generate.py
   → engine/guard.py → engine/execute.py → engine/context.py
   → api/chat.py → 前端 ChatView.vue
```

先看主干（谁调谁），再看枝叶（每个函数怎么实现）。**不要**从 `context.py` 的 BM25 数学开始读——那会让你以为这个项目的核心是算法。

---

## 附录 A：文件地图

| 文件 | 行数 | 职责 | 新手先读？ |
|---|---|---|---|
| `backend/app/config.py` | 88 | 所有配置项 | ✅ |
| `backend/app/models.py` | 82 | 数据表结构 | ✅ |
| `backend/app/engine/pipeline.py` | 188 | **主循环**，最重要 | ✅✅ |
| `backend/app/engine/generate.py` | 148 | 三个 prompt + 两段式 | ✅✅ |
| `backend/app/engine/guard.py` | 152 | 只读闸门 | ✅ |
| `backend/app/engine/execute.py` | 131 | 执行器 | ✅ |
| `backend/app/engine/context.py` | 249 | BM25 选表 + 上下文渲染 | 第二遍再读 |
| `backend/app/engine/semantics.py` | 91 | YAML 解析与渲染 | ✅ |
| `backend/app/engine/llm.py` | 310 | HTTP 客户端 + FakeModel | 按需 |
| `backend/app/api/chat.py` | 192 | SSE 端点 | ✅ |
| `backend/app/dialects.py` | 149 | 三种数据库的连接构造 | 按需 |
| `frontend/src/views/ChatView.vue` | — | 事件消费 | 按需 |

## 附录 B：配置项速查

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `SQLAGENT_READ_MAX_ROWS` | 200 | 单次查询最大行数 |
| `SQLAGENT_MAX_REPAIR` | 3 | 最多重写次数 |
| `SQLAGENT_SCHEMA_MAX_TABLES` | 8 | 送给模型的表数量上限 |
| `SQLAGENT_SCHEMA_SAMPLE_ROWS` | 3 | 每张表的采样行数 |
| `SQLAGENT_SCHEMA_CACHE_TTL` | 60 | 结构快照缓存秒数 |
| `SQLAGENT_QUERY_TIMEOUT` | 10 | 查询超时（秒） |
| `SQLAGENT_LLM_MODEL` | qwen-plus | 模型名 |
| `SQLAGENT_LLM_TEMPERATURE` | 0.0 | 采样温度 |
| `SQLAGENT_LLM_SEED` | 空 | 固定种子（评测时设 42） |
| `SQLAGENT_SEMANTICS_PATH` | `backend/data/semantics.yaml` | 语义层文件 |
| `SQLAGENT_ALLOW_REGISTRATION` | true | 是否开放注册 |

## 附录 C：术语表

| 术语 | 一句话解释 |
|---|---|
| **Agent** | 让模型自己决定下一步、调用工具、循环直到完成的系统 |
| **Pipeline / 脚手架** | 把步骤写死、只在固定位置调用模型的系统（本项目） |
| **BM25** | 一种基于词频和逆文档频率的文本相关性打分算法，搜索引擎的经典基础 |
| **fan-out** | 一对多 JOIN 后行数膨胀，导致聚合指标重复计算 |
| **few-shot** | 在 prompt 里给几个示例，让模型模仿 |
| **RAG** | 检索 + 生成：先找出相关资料塞进 prompt，再让模型回答 |
| **SSE** | Server-Sent Events，服务器单向推送，本项目用它做流式 |
| **Guardrail** | 护栏：限制模型输出能做什么的检查层 |
| **Eval / EX** | 评测 / 执行准确率（Execution Accuracy），比结果集是否一致 |
| **显式 vs 隐式反馈** | 用户点踩是显式；用户改完再问一遍是隐式（本项目只做了显式入口） |

## 附录 D：FAQ

**Q：为什么不用 LangChain / LlamaIndex？**
A：这个链路只有三次 HTTP 调用和一个循环，用框架会引入大量抽象。等你需要多工具、多步规划时再引入也不迟。

**Q：为什么不直接让模型输出 SQL 文本？**
A：见 1.4——需要附带 `explain` 和 `assumptions`，前端和审计都要用。

**Q：为什么自纠错只回灌错误，不回灌上一条 SQL？**
A：省 token。代价是模型可能重复犯同一个错。想改的话：在 `feedback` 里同时带上上一条 SQL（`write_sql` 加个参数即可）。

**Q：为什么 3 次就放弃？**
A：经验值。模型连续三次改不对，通常是上下文缺信息（比如表选错了），再试也是浪费 token。

**Q：这个项目最难的部分是什么？**
A：不是 BM25，也不是 prompt，而是**评测集**。demo 库是我们自己造的，知道正确答案；真实客户的库，你得先花时间定义"什么算对"。

---

**最后一句**：读懂这个项目不需要天赋，只需要按顺序读 `pipeline.py` → `generate.py` → `guard.py`，然后跑一遍第 6 章的实验 1 和 3。剩下的都是细节。