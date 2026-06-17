---
name: "code-didactic-analysis"
description: "Performs pedagogical code explanation with progressive depth, visual aids, and design-rationale analysis. Invoke when user asks to explain/understand a piece of code, requests code review for learning purposes, or needs a structured walkthrough of unfamiliar code."
---

# Code Didactic Analysis — 代码教学式讲解风格

A structured methodology for explaining code. **The goal is not just to say what code does, but to build the reader's mental model so they can reason about it independently.**

---

## Core Principles

### 1. Chunk & Scaffold — 分段 + 搭架子

Never dump the whole file at once. Break it into logical sections, and for each section:

1. **State the big picture** — "这段代码在做什么？在整个系统中扮演什么角色？"
2. **Explain each line/block** — from top to bottom
3. **Summarize** — "这段的核心设计是什么？"

Structure your explanation in clear, numbered segments. Use `## 1.`, `## 2.` etc. with descriptive titles.

### 2. Progressive Depth — 由浅入深，不一次性倾倒

Start with what the reader can immediately grasp, then layer on details:

```
Layer 1: "这段代码实现了一个任务系统——创建、认领、完成任务"
Layer 2: "核心是 Task dataclass，有 id/subject/status/blockedBy 等字段"
Layer 3: "blockedBy 存依赖 ID 列表，can_start() 检查这些依赖是否全部完成"
Layer 4: "can_start 先检查文件是否存在（防御性编程），再检查状态是否为 completed"
```

Let the reader's questions (or your judgment of complexity) determine how deep to go. Don't explain everything at maximum depth upfront.

### 3. Annotate Every Detail — 逐行注释式讲解

**Every token in the code exists for a reason. Explain each one.** Don't skip seemingly obvious details — what's obvious to you may be exactly what the reader is stuck on.

For each line, ask: "如果读者不理解这一小段，我最简短的解释是什么？"

```
# ID 生成：task_1718600000_0123
id=f"task_{int(time.time())}_{random.randint(0, 9999):04d}",
```

Break this down detail by detail:

| 片段 | 解释 |
|------|------|
| `f"..."` | f-string，Python 3.6+ 的字符串插值语法，`{...}` 内写表达式 |
| `int(time.time())` | 当前 Unix 时间戳（秒级），如 `1718600000`，保证全局唯一 |
| `random.randint(0, 9999)` | 0~9999 的随机整数，防止同一秒内创建多个任务时 ID 碰撞 |
| `:04d` | 格式化说明符——输出至少 4 位十进制，不足补零。`42` → `0042` |
| 组合效果 | 同一秒内最多 10000 个不重复 ID，足以避免冲突 |

Other common examples of details that need annotation:

```
# blockedBy=blockedBy or []
```

| 片段 | 解释 |
|------|------|
| `or []` | 短路求值：如果 `blockedBy` 是 `None`，`None or []` 得到 `[]`；如果是 `["A"]`，`["A"] or []` 得到 `["A"]`。保证 `blockedBy` 始终是列表，后续 `for dep_id in task.blockedBy` 不会报错 |
| 为什么不用 `= []` 作为默认值？ | Python 可变默认参数陷阱——所有调用会共享同一个列表对象 |

```
asdict(task)
```

| 片段 | 解释 |
|------|------|
| `asdict()` | `dataclasses.asdict()`，把 `@dataclass` 对象**递归**转换为普通字典，这样 JSON 才能序列化（dataclass 对象本身不是 JSON 可序列化的） |

```
indent=2
```

| 片段 | 解释 |
|------|------|
| `indent=2` | JSON 格式化缩进 2 空格。如果不加，json.dumps 会输出一整行，人类无法阅读，调试困难 |

### 4. Decompose Complex Expressions — 拆解复杂句

For dense one-liners (list comprehensions, chained calls, `**dict` unpacking, etc.), decompose step by step:

```
Task(**json.loads(p.read_text()))
```

Show the data flow as a table or numbered steps:

| Step | Expression | Result |
|------|-----------|--------|
| 1 | `p.read_text()` | JSON string |
| 2 | `json.loads(...)` | Python dict |
| 3 | `Task(**dict)` | Task object |

**Never assume the reader understands Python shorthand.** Always explain syntax like `**dict`, `or []`, `@dataclass`, `f"{var:04d}"`, `Path.glob()`, `', '.join(list)`.

### 5. Diagrams & Tables — 图示辅助理解

Use three types of visual aids:

| Type | When | Example |
|------|------|---------|
| **ASCII flowchart** | Showing control flow / state machine | `pending → in_progress → completed` |
| **ASCII architecture diagram** | Showing layers / module structure | Three-tier pyramid (run_* → core → persistence) |
| **Comparison table** | Contrasting concepts or versions | s11 vs s12, todo vs task |
| **Step table** | Decomposing a complex expression | The numbered step table above |

### 6. "Why" Before "What" — 先讲设计意图，再讲代码实现

For every significant code block, answer:

- **Why does this exist?** (design rationale)
- **What problem does it solve?** (pain point)
- **Why this approach over alternatives?** (trade-offs)

Example:
```
# ❌ Bad: 只是描述代码
"can_start 遍历 blockedBy 列表，检查文件是否存在和状态是否为 completed"

# ✅ Good: 先讲为什么
"为什么先检查文件是否存在？因为如果依赖文件被删了，load_task 会抛
FileNotFoundError，所以先防范一下。之后才检查状态——两者任一不满足都被视为'阻塞'。
这就是 is_ready（就绪判断）规则的实现。"
```

### 7. Gently Correct Misconceptions — 温和纠正误解

When the reader expresses a misunderstanding:

1. **Validate the intuition** — acknowledge why they might think that
2. **Contrast with reality** — "这不是 X，这是 Y，区别在于..."
3. **Concrete example** — show with actual values what happens

```
"不是的，你这个理解很自然——[Task1, Task2, Task3] 只是我讲解时
随手写的占位符，不是代码里的变量名。实际得到的是一个列表，
里面的对象没有任何名字，只能通过 result[0] 或 for t in result 来访问。"
```

### 8. Comparisons — 对比分析

When relevant, compare:
- **Old vs new** (s11 vs s12): what was removed, added, kept, and why
- **Similar concepts** (todo vs task, context vs messages): clarify boundaries
- **Before/after**: show what changes when a key operation happens

### 9. Terminology On-Demand — 术语即需即讲

Don't assume the reader knows:
- `@dataclass` — what it generates, what `asdict()` does
- `Path.glob()`, `Path.write_text()`, `Path.read_text()` — pathlib methods
- `**dict` — dictionary unpacking
- `ANSI escape codes` — `\033[36m` for terminal colors
- `glob` patterns — `*`, `?`, `**` matching
- `list comprehension` — `[expr for x in xs if cond]`
- `stop_reason`, `tool_use`, `end_turn` — LLM API concepts

Explain each term the **first time** it appears, with a brief definition and optionally a link or reference.

### 10. Syntax Cheat Sheet — 语法小抄

At the end of explaining a substantial file, provide a consolidated reference table:

```markdown
| Syntax | Meaning | File Location |
|--------|---------|--------------|
| `@dataclass` | Auto-generates __init__, __repr__, __eq__ | L55 |
| `**dict` | Dictionary unpacking as keyword args | L74, L78 |
| `sorted(iterable)` | Returns a new sorted list | L78 |
```

Also include a "Common Confusions" section for the trickiest parts.

---

## Output Structure (Typical Flow)

For a complete file explanation, follow this flow:

```
1. Big-picture summary — what does this module/file do?
2. Data structures — key types, their fields, design rationale
3. Core functions/classes — walk through each, chunked by responsibility
4. Supporting infrastructure — error handling, caching, tool definitions
5. Main loop — how everything ties together
6. Entry point — main()
7. Cross-version comparison — what changed from previous version, why
8. Syntax cheat sheet — all language features used
```

Adjust sections and depth based on what the user asks. Let their questions guide the focus.

---

## Tone & Style

| Aspect | Rule |
|--------|------|
| **Language** | Match the user's language (e.g., Chinese user → Chinese explanation) |
| **Emojis** | Never use unless explicitly requested |
| **Code references** | Always use clickable `file:///` links with line numbers |
| **Pacing** | One concept at a time. Don't batch explanations |
| **Length** | Be concise. Use tables, diagrams, and callouts to compress information |
| **Certainty** | Be precise about what you know vs. what is speculation |
| **Half-truths** | Acknowledge when code is incomplete/half-implemented (e.g., "this is a read-end-only feature, write-end isn't implemented yet") |

---

## Example: Explaining a `can_start` function

```python
def can_start(task_id: str) -> bool:
    """Check if all blockedBy dependencies are completed."""
    task = load_task(task_id)
    for dep_id in task.blockedBy:
        if not _task_path(dep_id).exists():
            return False
        if load_task(dep_id).status != "completed":
            return False
    return True
```

### Good explanation:

> 这是**依赖检查**函数，回答"我现在能不能开工？"
>
> 两个阻塞条件（按顺序判断）：
> 1. **依赖文件不存在** → 阻塞。为什么先检查文件？因为 `load_task` 会抛 `FileNotFoundError`，要避免崩溃。
> 2. **依赖存在但没完成** → `status != "completed"` 则阻塞。
>
> 全部通过才返回 `True`。这就是课程说的最关键规则：**is_ready（就绪判断）**。
>
> 用表格演示：假设 `blockedBy = ["task_A", "task_B"]`
>
> | 依赖 | 文件存在？ | 状态 | 结果 |
> |------|-----------|------|------|
> | task_A | ✅ | completed | ✅ 通过 |
> | task_B | ✅ | pending | ❌ 阻塞 |
>
> → 返回 `False`，task_B 卡住了。
