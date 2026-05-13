# s01 Agent Loop 学习笔记

> 基于 `s01-agent-loop-by-claude.py` 整理
> 核心：把"模型的动作意图"变成"真实执行结果"，再把结果送回模型继续推理

---

## 目录

1. [整体架构——一条消息的完整生命周期](#1-整体架构一条消息的完整生命周期)
2. [分段详解](#2-分段详解)
3. [核心数据结构](#3-核心数据结构)
4. [三种 ContentBlock 详解](#4-三种-contentblock-详解)
5. [常见问题 FAQ](#5-常见问题-faq)

---

## 1. 整体架构——一条消息的完整生命周期

### 1.1 一句话概括

> 这个文件做了一件事：**把"用户消息 → 模型回复 → 调工具 → 结果写回 → 继续"这条回路用代码实现出来。**

### 1.2 全景流程图

```
你输入 "帮我看看目录有什么"
         │
         ▼
history = [{"role": "user", "content": "帮我看看..."}]
         │
         ▼
state = LoopState(messages=history)
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│  agent_loop(state)                                       │
│                                                          │
│  ┌─ run_one_turn()   ← 第1轮 ────────────────────────┐  │
│  │  ① client.messages.create(...)   → Claude 回复     │  │
│  │  ② 追加 assistant 回复到 history                   │  │
│  │  ③ stop_reason == "tool_use"? → YES               │  │
│  │  ④ 执行 bash 命令 (ls -la)                         │  │
│  │  ⑤ 把 tool_result 写回 history                     │  │
│  │  ⑥ return True  → 继续                            │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─ run_one_turn()   ← 第2轮 ────────────────────────┐  │
│  │  ① client.messages.create(...)   → Claude 看到结果 │  │
│  │  ② Claude 给出最终回答 (没有 tool_use)              │  │
│  │  ③ stop_reason != "tool_use" → return False       │  │
│  └───────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
         │
         ▼
打印 Claude 的最终回答
```

### 1.3 最核心的 6 步（记熟）

```
① 把消息历史发给 Claude
② 把 Claude 的回复保存到历史
③ 如果 Claude 想调工具 → 执行工具
④ 把工具结果写回历史
⑤ 回到第①步
⑥ 如果 Claude 不再调工具 → 结束
```

> **关键中的关键**：第④步"把工具结果写回历史"如果漏了，下一轮 Claude 就不知道刚才执行的结果是什么。

### 1.4 这是 LangChain 吗？

**不是。** 这是直接基于 Anthropic 官方 SDK 手写的 Agent 循环。

| 对比 | 本代码 | LangChain |
|------|--------|-----------|
| import | `from anthropic import Anthropic` | `from langchain.agents import ...` |
| 架构 | 自己手写 while 循环 | AgentExecutor / Agent / LLMChain 三层抽象 |
| 学习目的 | 看清最小闭环长什么样 | 了解框架如何封装 |

---

## 2. 分段详解

### 2.1 文件头（第 1-11 行）

```python
#!/usr/bin/env python3
"""
s01_agent_loop.py - The Agent Loop
最小 agent 循环模式：
    user message
      -> model reply
      -> if tool_use: execute tools
      -> write tool_result back to messages
      -> continue
"""
```

文件头的注释已经画出了整条链路，先读它就能知道全局。

### 2.2 标准库导入（第 12-14 行）

```python
import os               # 获取当前目录、环境变量
import subprocess       # 执行 bash 命令（agent 干活的核心）
from dataclasses import dataclass  # 轻量数据类
```

**`subprocess`** 是 agent 能"真正做事"的原因——没有它，模型只能说话不能干活。

### 2.3 readline 终端优化（第 15-26 行）

```python
try:
    import readline
    readline.parse_and_bind('set bind-tty-special-chars off')
    # ... 更多绑定 ...
except ImportError:
    pass
```

**作用和 agent 核心逻辑无关**，只是改善终端交互体验：

- 方向键翻历史
- 退格键不乱码（macOS libedit 的 bug 修复）
- `try/except` 包起来说明：没有也不影响主功能

> 初学可以跳过的段落。

### 2.4 初始化 Anthropic 客户端（第 27-33 行）

```python
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)           # 从 .env 文件读取配置

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)  # 兼容第三方代理

client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]
```

| 代码 | 作用 |
|------|------|
| `load_dotenv()` | 读取项目根目录的 `.env` 文件 |
| `client = Anthropic(...)` | 创建 API 客户端 |
| `MODEL = os.environ["MODEL_ID"]` | 从环境变量读模型名 |

**`.env` 文件长这样：**

```bash
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_BASE_URL=https://你的代理地址
MODEL_ID=claude-sonnet-4-20250514
```

**两种场景的分支处理：**

| 场景 | `ANTHROPIC_BASE_URL` | 行为 |
|------|----------------------|------|
| 官方 API | 不设 | `Anthropic()` 自动读 `ANTHROPIC_API_KEY` |
| 第三方代理 | 有值 | 用代理地址创建客户端，删掉 `ANTHROPIC_AUTH_TOKEN`（某些代理不兼容） |

### 2.5 System Prompt 和 Tool 定义（第 34-48 行）

```python
SYSTEM = (
    f"You are a coding agent at {os.getcwd()}. "
    "Use bash to inspect and change the workspace. Act first, then report clearly."
)

TOOLS = [{
    "name": "bash",
    "description": "Run a shell command in the current workspace.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}]
```

#### SYSTEM

告诉 Claude：
- 它当前在哪个目录干活（`os.getcwd()` 动态注入）
- 它能用 bash 操作文件系统
- 策略：先行动再汇报

#### TOOLS

只定义了一个工具：`bash`。

| 字段 | 值 | 含义 |
|------|----|------|
| `name` | `"bash"` | 工具的名字，**给模型看的**（见 FAQ） |
| `description` | `"Run a shell command..."` | 告诉模型什么时候用这个工具 |
| `input_schema` | JSON Schema | 定义工具参数长什么样 |

#### 关于 tool name

`name` 是给**模型**看的，不是给代码看的。模型在训练数据里见过 "bash" 这个词，知道它是执行命令的工具。

> 如果把 `name` 改成 `"a"`，代码**技术上**能跑（因为只检查 `block.type == "tool_use"`，不检查 name），但模型很可能**不会主动调用**一个叫 `"a"` 的工具。名字起得好，模型才知道什么时候用它。

#### input_schema 详解

```python
"input_schema": {
    "type": "object",                          # 参数整体是一个对象 {}
    "properties": {
        "command": {"type": "string"}          # 里面有一个字段叫 command，类型是字符串
    },
    "required": ["command"],                   # command 是必填的
}
```

用函数签名类比就是：

```python
def bash(command: str):   # → 接收一个字符串参数
    ...
```

Claude 实际调用时发回的数据：

```python
{
    "type": "tool_use",
    "name": "bash",
    "input": {
        "command": "ls -la"    # ← 这就是上面定义的 command 参数字符串
    }
}
```

如果工具更复杂，可以加更多字段：

```python
"input_schema": {
    "type": "object",
    "properties": {
        "file_path": {"type": "string"},
        "content": {"type": "string"},
        "overwrite": {"type": "boolean"}       # 布尔类型
    },
    "required": ["file_path", "content"]       # overwrite 可选
}
```

### 2.6 LoopState —— 循环状态（第 50-54 行）

```python
@dataclass
class LoopState:
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None
```

| 字段 | 类型 | 默认值 | 作用 |
|------|------|--------|------|
| `messages` | `list` | 必填 | **整个对话历史**，也是下一轮模型的工作输入 |
| `turn_count` | `int` | `1` | 当前是第几轮 |
| `transition_reason` | `str \| None` | `None` | 本轮结束后**为什么还要继续**（如 `"tool_result"`） |

**为什么不用零散变量而要单独定义这个类？**

后面所有章节都要往这个类里加新字段：

- s02 → 加 `tool_router`
- s03 → 加 `plan_state`
- s06 → 加 `context_budget`
- s07 → 加 `permissions`

现在是朴素的 3 个字段，但它是扩展的起点。

### 2.7 run_bash() —— 执行命令（第 56-75 行）

```python
def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(item in command for item in dangerous):
        return "Error: Dangerous command blocked"

    try:
        result = subprocess.run(
            command,
            shell=True,              # 通过 shell 执行，支持管道、重定向
            cwd=os.getcwd(),         # 在当前目录下运行
            capture_output=True,     # 捕获 stdout + stderr
            text=True,               # 文本模式返回
            timeout=120,             # 120 秒超时
        )
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

    output = (result.stdout + result.stderr).strip()
    return output[:50000] if output else "(no output)"
```

这是 agent **真正干活**的函数。

**执行流程：**

```
收到命令 "ls -la"
    │
    ├─ 检查黑名单 ──→ 命中 → 返回 "Error: Dangerous command blocked"
    │
    ├─ subprocess.run(shell=True)  ──→ 超时 → 返回超时错误
    │                               ──→ 系统错误 → 返回错误信息
    │
    └─ 正常执行完毕
        │
        ├─ stdout + stderr 合并
        ├─ 截断到 50000 字符（防止撑爆上下文窗口）
        └─ 空结果返回 "(no output)"（不让模型收到空字符串迷惑）
```

**`shell=True` 意味着**：Claude 可以写 `ls -la | grep py` 这类需要 shell 解析的命令。

### 2.8 extract_text() —— 提取文本（第 77-83 行）

```python
def extract_text(content) -> str:
    if not isinstance(content, list):
        return ""
    texts = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            texts.append(text)
    return "\n".join(texts).strip()
```

**作用：从模型返回的 `content`（一个 ContentBlock 列表）中提取纯文本。**

模型返回的 `response.content` 可能混合多种 block（TextBlock + ToolUseBlock），只有 TextBlock 有 `.text` 属性。这个函数安全地只提取文本部分。

> 在文件末尾用到：循环结束后，从最后一条消息中提取模型的最终回答，打印给用户看。

### 2.9 execute_tool_calls() —— 执行工具调用（第 85-96 行）

```python
def execute_tool_calls(response_content) -> list[dict]:
    results = []
    for block in response_content:
        if block.type != "tool_use":
            continue          # 跳过 TextBlock，只处理 ToolUseBlock

        command = block.input["command"]
        print(f"\033[33m$ {command}\033[0m")    # 黄色打印命令
        output = run_bash(command)               # 真的执行！
        print(output[:200])                      # 打印输出前200字符

        results.append({
            "type": "tool_result",
            "tool_use_id": block.id,             # ← 绑定到对应的 tool_use
            "content": output,
        })
    return results
```

**逐步拆解：**

| 步骤 | 代码 | 说明 |
|------|------|------|
| 1 | `for block in response_content` | 遍历模型回复中的每个 block |
| 2 | `if block.type != "tool_use"` | 跳过 TextBlock（纯文本回复），只处理工具调用 |
| 3 | `command = block.input["command"]` | 取出 Claude 想执行的命令字符串 |
| 4 | `print("\033[33m$ ...\033[0m")` | 黄色打印命令——能实时看到模型在做什么 |
| 5 | `output = run_bash(command)` | **真正在本地执行这条命令** |
| 6 | `print(output[:200])` | 打印执行结果的前 200 字符 |
| 7 | 构造 `tool_result` | 包装成标准格式，`tool_use_id` 要和上面的 `block.id` 一致 |

**`tool_use_id` 为什么重要？**

Claude 可能一次发多个工具调用。每条工具结果必须告诉 Claude "这是你刚才哪次调用的结果"。`tool_use_id` 就是做这个匹配的。

### 2.10 run_one_turn() —— 执行一轮（第 98-118 行）

```python
def run_one_turn(state: LoopState) -> bool:
```

这是整个 agent 循环的**最小单元**。返回 `True` 表示"还要继续"，`False` 表示"结束了"。

**第 1 步：调用模型**

```python
    response = client.messages.create(
        model=MODEL,
        system=SYSTEM,
        messages=state.messages,    # ← 所有历史当上下文
        tools=TOOLS,
        max_tokens=8000,
    )
```

`state.messages` 里装着全部历史——包括用户问题、之前的 assistant 回复、之前的工具结果。模型基于这些继续推理。

**第 2 步：保存回复**

```python
    state.messages.append({"role": "assistant", "content": response.content})
```

把模型的回复写回历史。**初学者最容易漏这一步**——少了它，下一轮模型就不知道自己上轮说过什么，上下文就断了。

**第 3 步：判断是否继续**

```python
    if response.stop_reason != "tool_use":
        state.transition_reason = None
        return False
```

`response.stop_reason` 告诉本轮模型为什么停下：

| stop_reason | 含义 | 要不要继续？ |
|-------------|------|-------------|
| `"tool_use"` | 模型想调工具 | ✅ 继续（还有活没干完） |
| `"end_turn"` | 模型觉得做完了 | ❌ 结束，打印最终回答 |

**第 4 步：执行工具**

```python
    results = execute_tool_calls(response.content)
```

调用上面 2.9 的函数，真的去执行模型要调的 bash 命令。

**第 5 步：检查执行结果**

```python
    if not results:
        state.transition_reason = None
        return False
```

防御检查——如果模型说想调工具但实际没发 `tool_use` block，或者所有执行都失败，就终止。

**第 6 步：写回结果，准备下一轮**

```python
    state.messages.append({"role": "user", "content": results})
    state.turn_count += 1
    state.transition_reason = "tool_result"
    return True
```

**这是整个 agent 循环最重要的一步。**

工具结果以 `{"role": "user", "content": [tool_result块]}` 的形式写回历史。下一轮调用模型时，Claude 就能看到自己的命令产生了什么输出。

> **为什么用 `role: "user"`？** 这是 Anthropic API 的约定——`tool_result` 要放在 `user` 角色的消息里。

### 2.11 agent_loop() —— 循环驱动器（第 120-122 行）

```python
def agent_loop(state: LoopState) -> None:
    while run_one_turn(state):
        pass
```

**最短但最重要的函数：**

- `while run_one_turn(state)` —— 只要返回 `True` 就继续下一轮
- 返回 `False` —— 循环结束
- `pass` —— 循环体是空的，所有逻辑都在 `run_one_turn` 里

### 2.12 main 入口（第 124-134 行）

```python
if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")    # 青色提示符
        except (EOFError, KeyboardInterrupt):
            break

        if query.strip().lower() in ("q", "exit", ""):
            break

        history.append({"role": "user", "content": query})
        state = LoopState(messages=history)
        agent_loop(state)

        final_text = extract_text(history[-1]["content"])
        if final_text:
            print(final_text)
        print()
```

**外层 while：多次对话**

```
┌─────────────────────────────────────┐
│  while True:                        │
│      s01 >> 你输入问题              │
│           ↓                         │
│      history.append(你的问题)       │
│      state = LoopState(history)     │
│      agent_loop(state)  ← 核心循环  │
│           ↓                         │
│      打印最终回答                    │
│      ─────────────────────           │
│      s01 >> 下一个问题...           │
└─────────────────────────────────────┘
```

**退出方式：**

- 输入 `q` / `exit` / 直接回车
- `Ctrl+D` (EOFError) 或 `Ctrl+C` (KeyboardInterrupt)

**注意 `history` 的共享引用：**

```python
history = []
state = LoopState(messages=history)   # → 同一个列表对象
agent_loop(state)
# 此时 history 已经被 agent_loop 里的 run_one_turn 修改了
# (中间的所有 assistant 回复和 tool_result 都在里面)
```

`history` 和 `state.messages` 指向的是**同一个列表对象**。`agent_loop` 对 `state.messages` 的所有修改（追加 assistant 回复、追加 tool_result），都直接反映在 `history` 里。所以最后 `history[-1]` 就是最终消息。

---

## 3. 核心数据结构

### 3.1 Message 格式

```python
{"role": "user", "content": "纯文本字符串"}
{"role": "assistant", "content": [ContentBlock, ContentBlock, ...]}  # 列表
{"role": "user", "content": [ToolResultBlock, ...]}                  # 列表
```

**消息历史不是聊天记录展示层，而是模型下一轮要读的工作上下文。**

### 3.2 完整一轮的消息变化

**初始状态：**

```python
[
    {"role": "user", "content": "帮我看看目录"}
]
```

**第 1 轮之后：**

```python
[
    {"role": "user", "content": "帮我看看目录"},
    {"role": "assistant", "content": [TextBlock, ToolUseBlock]},    ← 新增
    {"role": "user", "content": [ToolResultBlock]},                 ← 新增
]
```

**第 2 轮（最终）之后：**

```python
[
    {"role": "user", "content": "帮我看看目录"},
    {"role": "assistant", "content": [TextBlock, ToolUseBlock]},
    {"role": "user", "content": [ToolResultBlock]},
    {"role": "assistant", "content": [TextBlock]},                   ← 最终回答
]
```

---

## 4. 三种 ContentBlock 详解

### 4.1 为什么叫 ContentBlock？

`response.content` 是一个 **列表**，里面每个元素是一个 **ContentBlock**。

模型一次回复可以同时"说话"和"调工具"，所以 content 是一个列表：

```python
response.content = [
    ContentBlock_1,    # 可能是 TextBlock（说话）
    ContentBlock_2,    # 可能是 ToolUseBlock（调工具）
    ...
]
```

### 4.2 对照表

| Block 类型 | 出现时机 | 关键字段 | 类比 |
|-----------|---------|----------|------|
| **TextBlock** | 模型想**说话**时 | `type: "text"`, `text: "..."` | 模型在"说" |
| **ToolUseBlock** | 模型想**调工具**时 | `type: "tool_use"`, `id`, `name`, `input` | 模型在"要" |
| **ToolResultBlock** | 你**把结果写回**时 | `type: "tool_result"`, `tool_use_id`, `content` | 你在"喂结果" |

### 4.3 完整往返示例

**第 1 步：Claude 回复**

```python
response.content = [
    TextBlock(type="text", text="我来看看当前目录有什么。"),
    ToolUseBlock(
        type="tool_use",
        id="toolu_abc123",              # ← 记住这个 ID
        name="bash",
        input={"command": "ls -la"}
    )
]
```

**第 2 步：代码执行工具，构造 ToolResultBlock**

```python
{
    "type": "tool_result",
    "tool_use_id": "toolu_abc123",       # ← 和上面的 id 一致
    "content": "total 24\n-rw-r--r-- ..."
}
```

**第 3 步：写回历史，下一轮发给 Claude**

Claude 看到 `tool_use_id == "toolu_abc123"`，就知道"这是我刚才那条 ls 的结果"，然后基于结果推理下一步。

---

## 5. 常见问题 FAQ

### Q1：这个文件是 LangChain 吗？

不是。没有任何 LangChain 的 import。这是裸调 Anthropic SDK，手写的 while 循环。

### Q2：如果我把工具名字改成 "a" 会怎样？

代码技术上能跑（引擎不检查 name），但模型**很可能不会主动调用**一个叫 `"a"` 的工具。因为模型根据名字判断什么时候用这个工具。名字要语义明确。

### Q3：`"type": "object"` 是什么意思？

这是 **JSON Schema** 写法：

```python
"input_schema": {
    "type": "object",                              # 参数整体是个对象 {}
    "properties": {
        "command": {"type": "string"}              # 里面有一个字段 command，字符串类型
    },
    "required": ["command"]                        # command 必填
}
```

等价于函数签名 `def bash(command: str)`。

### Q4：如果工具结果不写回 messages 会怎样？

**模型下一轮就看不到执行结果。** 它会以为自己调了工具但没拿到结果，然后可能重复调同一个工具，或者胡乱猜测输出。

### Q5：如果 assistant 回复不写回 messages 会怎样？

模型下一轮不知道自己刚才说过什么，上下文断层，推理质量急剧下降。

### Q6：`(no output)` 和空字符串有什么区别？

空字符串 = "好像没输出，可能是出错了？"
`(no output)` = "命令确实执行了，但没产生任何输出，这是正常情况"

让模型能区分这两种情况，避免困惑。

### Q7：为什么用 role: "user" 装 tool_result？

Anthropic API 的约定。tool_result 块必须放在 `role: "user"` 的消息里。
