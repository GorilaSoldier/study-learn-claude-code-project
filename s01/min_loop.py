# 定义智能体的主循环函数，接收一个 state（状态）参数
def agent_loop(state):
    # 无限循环：持续和大模型交互，直到不需要调用工具就退出
    while True:
        # 1. 调用大模型API，发送请求
        response = client.messages.create(
            model=MODEL,        # 指定使用的大模型（比如GPT/ Claude）
            system=SYSTEM,       # 系统提示词（AI的身份、规则）
            messages=state["messages"],  # 【关键】发送完整的对话历史
            tools=TOOLS,         # 给AI注册的工具（搜索、计算器等）
            max_tokens=8000,     # 最大响应长度
        )

        # 2. 把大模型的回复，存入对话历史（角色：AI助手）
        state["messages"].append({
            "role": "assistant",
            "content": response.content,
        })

        # 3. 判断AI是否需要调用工具
        # 如果停止原因不是「工具调用」，说明AI直接回复了文本，结束循环
        if response.stop_reason != "tool_use":
            state["transition_reason"] = None
            return  # 退出循环，函数结束

        # 4. 如果AI需要调用工具 → 执行工具
        results = []
        # 遍历模型返回的内容块（response.content 是一个列表）
        for block in response.content:
            # 筛选出「工具调用」类型的块
            if block.type == "tool_use":
                # 执行工具，获取执行结果
                output = run_tool(block)
                # 把工具结果组装成标准格式
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,  # 对应AI要调用的那个工具
                    "content": output,        # 工具执行后的输出
                })

        # 5. 把工具执行结果，作为「用户消息」存入对话历史
        state["messages"].append({"role": "user", "content": results})
        # 6. 更新状态：对话轮次+1，标记本轮是工具调用返回
        state["turn_count"] += 1
        state["transition_reason"] = "tool_result"
