# Always-Stream 重构计划：消除关键词门控

## 背景

Story 1.6 稳定化期间引入了 `_should_use_tool_loop_for_streaming()` 关键词门控，在流式路径入口通过关键词匹配决定走 fast path（直接流式）还是 tool-loop path。

**问题**：
- 假阴性：用户消息不含关键词但需要工具时，走 fast path，工具不被调用
- 维护成本：每新增工具都要更新关键词集合 + 更新测试消息文案
- 偏离 Story 1.4 原始设计和行业主流做法

**方案**：采用 always-stream 模式——所有流式请求都用 `stream=True` + `tools`，通过 chunk 累积判断是 text 还是 tool_calls，消除关键词预分类。

## 核心设计

```
当前：  keyword gate → fast path(无工具) | tool-loop(非流式决策 → 工具执行 → 流式输出)

重构后：always stream(tools) → 逐 chunk 转发 + 累积
         → finish_reason == "stop"       → 已经逐 chunk 转发完毕，结束
         → finish_reason == "tool_calls" → stream_chunk_builder 重组
             → 推送 status events → 执行工具 → 再次 stream(tools)
             → 循环直到 "stop"
```

**关键优势**：
- text 响应零额外延迟（chunk 边收边转发）
- tool_calls 由 LLM 决定，无假阴性
- 删除 `_TOOL_INTENT_KEYWORDS` 和 `_should_use_tool_loop_for_streaming()`，消除维护契约

## 执行步骤

### Step 1：重写 `_agent_loop()` 内部逻辑

**文件**：`mentor-agent-service/app/services/agent_service.py`

**删除**（约 35 行）：
- `_TOOL_INTENT_KEYWORDS` 常量（L27-51）
- `_should_use_tool_loop_for_streaming()` 函数（L54-60）
- `_agent_loop()` 内的 fast path 分支（L182-197）

**重写** `_agent_loop()` 核心逻辑为 always-stream 模式：

```python
async def _agent_loop() -> None:
    try:
        tools = registry.get_all_schemas()
        iteration = 0

        while iteration < settings.max_tool_iterations:
            logger.info("tool-loop(stream) iteration=%s", iteration + 1)

            # Always stream with tools
            stream_result = await llm_service.stream_chat_completion(
                messages=messages, model=model,
                temperature=temperature, max_tokens=max_tokens,
                tools=tools, tool_choice="auto",
            )
            if isinstance(stream_result, str):
                await queue.put(make_status_event(f"⚠️ {stream_result}", resolved_model))
                break

            # Accumulate chunks, forwarding text deltas immediately
            chunks = []
            async for chunk in stream_result:
                chunks.append(chunk)
                chunk_dict = chunk.model_dump(exclude_none=True)

                # Forward text content deltas to client in real-time
                delta = chunk_dict.get("choices", [{}])[0].get("delta", {})
                if delta.get("content"):
                    await queue.put(f"data: {json.dumps(chunk_dict)}\n\n")

            # Rebuild complete response from chunks
            import litellm
            rebuilt = litellm.stream_chunk_builder(chunks, messages=messages)

            if not getattr(rebuilt, "choices", None):
                await queue.put(make_status_event("⚠️ Error: LLM returned empty choices", resolved_model))
                break

            choice = rebuilt.choices[0]
            finish_reason = choice.finish_reason

            if finish_reason == "tool_calls" and getattr(choice.message, "tool_calls", None):
                # Tool calls detected — push status, execute tools, loop
                await queue.put(make_status_event("💭 Thinking...", resolved_model))
                messages.append(choice.message.model_dump())

                for tool_call in choice.message.tool_calls:
                    fn_name = tool_call.function.name
                    await queue.put(make_status_event(f"🔧 Running {fn_name}...", resolved_model))
                    tool_result = await _execute_tool(fn_name, tool_call.function.arguments)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": fn_name,
                        "content": tool_result,
                    })
                iteration += 1
                continue

            # finish_reason == "stop" — text chunks already forwarded above
            break
        else:
            await queue.put(make_status_event(
                f"⚠️ Tool loop reached maximum {settings.max_tool_iterations} iterations",
                resolved_model,
            ))

        await queue.put(make_done_event())
    except Exception as exc:
        logger.exception("Agent loop error: %s", exc)
        await queue.put(make_status_event(f"⚠️ Error: {exc}", resolved_model))
        await queue.put(make_done_event())
    finally:
        done.set()
        await queue.put(None)
```

**注意事项**：
- text delta 边收边转发：`if delta.get("content")` 时立即 `queue.put()`
- tool_call delta **不转发**：tool_calls 的 chunk 只累积不转发（用户不需看到 function arguments）
- `litellm.stream_chunk_builder(chunks)` 重组完整 response 对象，提取 `finish_reason` 和 `tool_calls`
- 非流式 `get_chat_completion_with_tools()` 在流式路径中**不再调用**（仅保留给 `run_agent_loop()` 非流式路径）

### Step 2：更新测试

**文件**：`tests/unit/test_agent_service_streaming.py`

- **恢复被关键词门控修改过的 6 处消息文案**：回到原始简短文案（"Hi"、"Loop"、"Crash" 等），因为不再有关键词过滤
- **mock 改变**：现在所有路径都走 `llm_service.stream_chat_completion()`，不再走 `get_chat_completion_with_tools()`
  - mock `stream_chat_completion` 返回 async iterator of chunks
  - mock `litellm.stream_chunk_builder` 返回重组后的 response 对象
- **新增测试**：`test_tool_call_detected_via_stream_chunk_builder` — 验证流式 chunk 累积后正确检测 tool_calls

**文件**：`tests/unit/test_agent_service.py`（L303）
- 恢复消息文案（仅影响走 streaming 路径的那 1 个测试）

**文件**：`tests/unit/test_agent_persona_injection.py`（streaming path test）
- 恢复消息文案

**文件**：`tests/integration/test_sse_status_flow.py`
- 无需改动（端到端 HTTP 测试，不受内部路由变化影响）

**文件**：`tests/integration/test_rag_tool_integration.py`
- 无需改动（同上）

### Step 3：验证

1. `cd mentor-agent-service && python -m pytest tests/ -v` — 全量通过
2. 确认无 `_TOOL_INTENT_KEYWORDS` 和 `_should_use_tool_loop_for_streaming` 残留引用

## 关键文件

| 文件 | 改动类型 |
|---|---|
| `app/services/agent_service.py` | 删除关键词门控 + 重写 `_agent_loop()` |
| `tests/unit/test_agent_service_streaming.py` | mock 调整 + 消息文案恢复 |
| `tests/unit/test_agent_service.py` | 1 处消息文案恢复 |
| `tests/unit/test_agent_persona_injection.py` | 1 处消息文案恢复 |

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| `stream_chunk_builder` 对 Anthropic via proxy 重组 tool_calls 不正确 | Step 1 实施后用集成测试验证；如果不可靠，自行实现 chunk 累积逻辑（~20 行） |
| 纯文本响应的 text delta 和 rebuilt response 重复 | text delta 已经边收边转发，rebuilt 后检测到 `finish_reason == "stop"` 直接 break，不重复发送 |
| tool_call chunk 被错误转发给客户端 | `if delta.get("content")` 守卫确保只转发有 content 的 chunk |

## 不在本次范围

- litellm Python 库替换（单独讨论）
- `run_agent_loop()`（非流式路径）不改动
- Story 1.4 文档不需要再次更新（已在本次重构前完成回写）
