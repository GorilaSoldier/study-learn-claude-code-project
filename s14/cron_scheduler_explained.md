# Cron Scheduler 代码讲解

> 文件：`python s14_cron_scheduler.py` 第 270 ~ 429 行
> 整理自与 AI 的对话，供跨设备继续追问参考

---

## 整体架构

```
┌─────────────────────────────────────────────────┐
│                 Cron Scheduler                    │
│                                                   │
│  schedule_job() ──→ scheduled_jobs{} ──→ cron_   │
│                      (全局注册表)     scheduler_  │
│                                        loop()      │
│  cancel_job()  ──→ 删除注册表条目       │           │
│                                        ▼           │
│                        cron_queue[] ← 放行匹配的   │
│                                        job          │
│                        (线程安全队列)               │
│                                        ▼           │
│                        queue_processor_loop()      │
│                        → 唤醒 agent 处理            │
└─────────────────────────────────────────────────┘
```

---

## 1. 数据结构与全局状态 (L270-L288)

```python
DURABLE_PATH = WORKDIR / ".scheduled_tasks.json"
@dataclass
class CronJob:
    id: str
    cron: str        # "0 9 * * *"
    prompt: str      # message to inject when fired
    recurring: bool  # True = recurring, False = one-shot
    durable: bool    # True = persist to disk
scheduled_jobs: dict[str, CronJob] = {}
cron_queue: list[CronJob] = []
cron_lock = threading.Lock()
agent_lock = threading.Lock()
_last_fired: dict[str, str] = {}  # job_id → "YYYY-MM-DD HH:MM"
```

| 元素 | 解释 |
|------|------|
| `DURABLE_PATH` | 持久化文件路径，`WORKDIR / ".scheduled_tasks.json"`，pathlib 的 `/` 是路径拼接 |
| `@dataclass CronJob` | 数据类，自动生成 `__init__`、`__repr__`、`__eq__` |
| `id: str` | 唯一标识，如 `"cron_000042"` |
| `cron: str` | 5 字段 cron 表达式 |
| `prompt: str` | 触发时要注入的消息 |
| `recurring: bool` | True=重复执行，False=一次性 |
| `durable: bool` | True=持久化到磁盘 |
| `scheduled_jobs` | 全局注册表，Dict[str, CronJob] |
| `cron_queue` | 线程安全队列（list + 手动加锁） |
| `cron_lock` | 保护调度数据的线程锁 |
| `agent_lock` | 保护 AI agent 执行的线程锁 |

**为什么两把锁？** 调度数据和 agent 执行是不同资源，分开加锁避免不必要阻塞。

---

## 2. 单字段匹配：`_cron_field_matches` (L289-L307)

```python
def _cron_field_matches(field: str, value: int) -> bool:
```

判断一个 cron 字段（如 `"*/15"`）是否匹配给定数值。

| 条件 | 示例 | 匹配逻辑 |
|------|------|---------|
| `field == "*"` | `"*"` | 通配符，永远匹配 |
| `field.startswith("*/")` | `"*/15"` | `value % step == 0`，每15分钟 |
| `"," in field` | `"1,3,5"` | 用递归检查每个值，任一匹配即可 |
| `"-" in field` | `"9-17"` | `int(lo) <= value <= int(hi)` |
| 否则 | `"30"` | 精确匹配 `value == int(field)` |

**逗号处为何用递归？** 因为 `"*/10"` 或 `"1-5"` 本身也包含特殊语法，不能直接比相等，递归让每种语法走自己的分支。

**`any(...)`**：Python 内置，迭代器中任一元素为 True 则返回 True。

---

## 3. 完整 cron 表达式匹配：`cron_matches` (L308-L339)

```python
def cron_matches(cron_expr: str, dt: datetime) -> bool:
```

### 5 个字段

| 位置 | 字段 | 范围 | 含义 |
|------|------|------|------|
| 0 | minute | 0-59 | 分钟 |
| 1 | hour | 0-23 | 小时 |
| 2 | dom | 1-31 | day-of-month |
| 3 | month | 1-12 | 月份 |
| 4 | dow | 0-6 | day-of-week (0=周日) |

### 星期几坐标转换

```python
dow_val = (dt.weekday() + 1) % 7
```

| 真实星期 | Python weekday() | cron dow |
|---------|-----------------|----------|
| 周日 | 6 | 0 |
| 周一 | 0 | 1 |
| 周二 | 1 | 2 |
| ... | ... | ... |
| 周六 | 5 | 6 |

### DOM 和 DOW 的 OR 逻辑（核心设计）

标准 cron 语义：**分钟、小时、月用 AND；日和星期用 OR**。

| DOM 状态 | DOW 状态 | 结果 |
|----------|---------|------|
| `*` | `*` | 每天匹配 |
| `*` | 有约束 | 只看 DOW |
| 有约束 | `*` | 只看 DOM |
| 有约束 | 有约束 | **两者任一匹配即可 (OR)** |

为什么用 OR？例子：`"0 9 15 * 5"` 意思是"每月15号以及每个周五"，不是"每月15号且恰好是周五"——后者可能几年碰不上一次。

---

## 4. 单字段验证：`_validate_cron_field` (L340-L380)

```python
def _validate_cron_field(field: str, lo: int, hi: int) -> str | None:
```

与 `_cron_field_matches` 结构对称，但返回 `None`（合法）或 `str`（错误信息）。

| 语法 | 验证逻辑 |
|------|---------|
| `"*"` | 永远合法 |
| `"*/5"` | step 是否为正整数 |
| `"1,3,5"` | 递归验证每个值 |
| `"1-5"` | 起止在 `[lo, hi]` 内，且起始 ≤ 结束 |
| `"30"` | 是数字且在范围内 |

`str | None`：Python 3.10+ 类型联合，等价于 `Optional[str]`。

---

## 5. 完整验证：`validate_cron` (L381-L387)

```python
bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
names = ["minute", "hour", "day-of-month", "month", "day-of-week"]
for i, (field, (lo, hi), name) in enumerate(zip(fields, bounds, names)):
    err = _validate_cron_field(field, lo, hi)
    if err:
        return f"{name}: {err}"
return None
```

### 关于 `for i, (field, (lo, hi), name) in enumerate(zip(...))` 的详解

`zip(fields, bounds, names)` 把三个列表按位置一一配对：

| 第几次 | field | bound | name |
|--------|-------|-------|------|
| 0 | `"0"` | `(0,59)` | `"minute"` |
| 1 | `"9"` | `(0,23)` | `"hour"` |
| 2 | `"15"` | `(1,31)` | `"day-of-month"` |
| ... | ... | ... | ... |

**多重嵌套解包**：

```
enumerate 每次产出:  (i,  (field,   (lo, hi),   name) )
                       ↑    ↑         ↑           ↑
                      索引  字段值   范围(拆成lo,hi)  字段名
```

**`i` 是多余的**——循环体内没有用到 `i`，可以简化为：

```python
for field, (lo, hi), name in zip(fields, bounds, names):
    ...
```

等价于：

```python
for triple in zip(fields, bounds, names):
    field = triple[0]
    lo = triple[1][0]
    hi = triple[1][1]
    name = triple[2]
```

---

## 6. 持久化：`save_durable_jobs` / `load_durable_jobs` (L388-L409)

### 保存

```python
def save_durable_jobs():
    durable = [asdict(j) for j in scheduled_jobs.values() if j.durable]
    DURABLE_PATH.write_text(json.dumps(durable, indent=2))
```

| 片段 | 解释 |
|------|------|
| `[asdict(j) for j in scheduled_jobs.values() if j.durable]` | 列表推导式：遍历所有 job，取 durable=True 的，用 `asdict()` 转字典 |
| `asdict()` | `dataclasses.asdict()`，递归地将 dataclass 转成普通 dict |
| `json.dumps(..., indent=2)` | JSON 格式化，缩进 2 空格 |
| `DURABLE_PATH.write_text(...)` | Pathlib 方法，写文件 |

**`scheduled_jobs.values()`** 返回字典的所有 value（即 CronJob 对象），不会重复。dict 的 key（job_id）本身就是唯一的，每个 CronJob.id 也是唯一的。

**注意：`save_durable_jobs()` 是覆盖写**。`write_text` 会截断文件再写入，始终保证磁盘上的 JSON 与内存中 `scheduled_jobs` 的状态完全一致。如果改成追加写，删 job 时无法清除已写入的记录。

### 加载

```python
def load_durable_jobs():
    if not DURABLE_PATH.exists():
        return
    try:
        jobs = json.loads(DURABLE_PATH.read_text())
        for j in jobs:
            job = CronJob(**j)
            err = validate_cron(job.cron)
            if err:
                print(f"  \033[31m[cron] skipping invalid job {job.id}: {err}\033[0m")
                continue
            scheduled_jobs[job.id] = job
```

`CronJob(**j)` 中的 `**j` 是**字典解包**，等价于：
```python
CronJob(id=j["id"], cron=j["cron"], prompt=j["prompt"], recurring=j["recurring"], durable=j["durable"])
```

**为什么加载时还要校验？** 磁盘文件可能被手动编辑引入语法错误，防御性编程。

**`\033[...m`** — ANSI 转义码：
- `\033[31m` → 红色
- `\033[35m` → 紫色
- `\033[0m` → 重置

---

## 7. 注册与取消：`schedule_job` / `cancel_job` (L410-L429)

### 注册

```python
def schedule_job(cron: str, prompt: str, recurring: bool = True,
                 durable: bool = True) -> CronJob | str:
```

返回类型 `CronJob | str`：成功返回对象，失败返回错误字符串。

```python
id=f"cron_{random.randint(0, 999999):06d}"
```

| 片段 | 解释 |
|------|------|
| `f"..."` | f-string 插值 |
| `random.randint(0, 999999)` | 0~999999 随机数 |
| `:06d` | 至少 6 位十进制，补零，如 `42` → `"000042"` |

```python
with cron_lock:
    scheduled_jobs[job.id] = job
```

`with lock:` 进入时自动 `acquire()`，退出时自动 `release()`。

### 取消

```python
def cancel_job(job_id: str) -> str:
    with cron_lock:
        job = scheduled_jobs.pop(job_id, None)
```

**`dict.pop(key, default)`** — 删除 key 并返回 value，不存在返回默认值（不抛 `KeyError`）。

---

## 语法小抄

| 语法 | 含义 | 行号 |
|------|------|------|
| `@dataclass` | 自动生成 `__init__`、`__repr__`、`__eq__` | L273 |
| `asdict(obj)` | dataclass 递归转为普通 dict | L390 |
| `**dict` | 字典解包为关键字参数 | L399 |
| `Path / "subdir"` | Pathlib 路径拼接 | L270 |
| `f"{value:06d}"` | f-string 格式化：至少6位补零 | L417 |
| `str \| None` | Python 3.10+ 类型联合 | L340 |
| `any(iterable)` | 任一元素为 True 则返回 True | L302 |
| `dict.pop(key, default)` | 删除并返回 key 的 value | L422 |
| `\033[31m` | ANSI 终端红色转义码 | L402 |
| `threading.Lock()` | 线程锁 | L285 |
| `with lock:` | 上下文管理器自动加解锁 | L420 |
| `zip(a, b, c)` | 把多个列表按位置配对 | L364 |
| `enumerate(xs)` | 给迭代器加索引 | L364 |
| `(field, (lo, hi), name)` | 多重嵌套解包 | L364 |

## 常见困惑

**Q: `scheduled_jobs.values()` 会有相同 job_id 吗？**
A: 不会。dict 的 key 是唯一的，每个 CronJob.id 也是随机生成的，不会重复。

**Q: `save_durable_jobs()` 是追加写还是覆盖写？**
A: **覆盖写**。`Path.write_text()` 会截断文件再写入，始终与内存状态保持一致。

**Q: 为什么有 `cron_lock` 和 `agent_lock` 两把锁？**
A: 保护不同资源。调度数据和 agent 执行互不干扰，分开加锁避免不必要阻塞。
