# TD-007 演进：Buffer+Discard → 直接流式输出

**状态**: ❌ 已回退 (2026-02-23) — 双重回复问题，恢复 buffer+discard + fast path 启发式

**回退原因**: 直接流式输出在 LLM 先生成完整回答再调工具的场景下产生双重回复（用户看到两段完整但不同的回答）。Open WebUI 无法区分 preamble 和 final answer，这是业界公认难题（LangChain #34491, Google ADK #3697）。恢复方案：tool loop 使用 buffer+discard（OpenAI 惯例 content=null），简单对话走 fast path 逐 token 流式。

## Context

**TD-007** 记录了当前 streaming agent loop 的 Buffer+Discard 策略：每轮迭代缓冲所有 content chunks，`finish_reason=="stop"` 时一次性 flush，`finish_reason=="tool_calls"` 时 discard。

**用户痛点**：回复一次性全部显示，即使是简单问答（无工具调用），也要等 LLM 生成完毕才看到内容。体验远不如正常 Claude 聊天的逐 token 流式输出。

**决策**：采用"直接流式输出"方案（用户从 3 个选项中选定），接受工具调用时用户可能先看到一小段中间文字再看到工具执行状态的 trade-off。

## 当前行为 vs 目标行为

### 当前 (Buffer+Discard)

```
用户发消息 → LLM 开始输出
  ├─ content chunks 全部缓冲到 buffered_content[]
  └─ 等待整个流结束
       ├─ finish_reason="stop"       → 一次性 flush 全部 chunks 给客户端
       └─ finish_reason="tool_calls" → 丢弃 buffered_content，执行工具，下一轮
```

效果：用户等 3-5 秒后看到全部回答一次性弹出。

### 目标 (直接流式)

```
用户发消息 → LLM 开始输出
  ├─ content chunks 实时推送给客户端 (await queue.put())
  └─ 等待整个流结束
       ├─ finish_reason="stop"       → 无需额外操作，已流完
       └─ finish_reason="tool_calls" → content 已发送（用户看到）
            → strip content from message history（防止下一轮 LLM 延续不可见上下文）
            → 执行工具，下一轮
```

效果：用户实时看到 LLM 逐 token 输出。工具调用场景下用户可能先看到 "好的，让我帮你查一下..." → 💭 Thinking... → 🔧 Running search_knowledge_base... → 最终回答。

## 改动范围

### 1. `agent_service.py` — `_agent_loop()` 内循环

**文件**: `mentor-agent-service/app/services/agent_service.py:210-289`

#### 1a. 移除 buffer，改为直接推送

```python
# 当前
buffered_content: list[str] = []
async for chunk in stream_result:
    chunks.append(chunk)
    chunk_dict = chunk.model_dump(exclude_none=True)
    choices = chunk_dict.get("choices", [])
    if choices and choices[0].get("delta", {}).get("content"):
        buffered_content.append(f"data: {json.dumps(chunk_dict)}\n\n")

# 改为
has_streamed_content = False
async for chunk in stream_result:
    chunks.append(chunk)
    chunk_dict = chunk.model_dump(exclude_none=True)
    choices = chunk_dict.get("choices", [])
    if choices and choices[0].get("delta", {}).get("content"):
        await queue.put(f"data: {json.dumps(chunk_dict)}\n\n")
        has_streamed_content = True
```

#### 1b. stream_chunk_builder 错误处理

```python
# 当前
except Exception as exc:
    if buffered_content:
        for event in buffered_content:
            await queue.put(event)
    else:
        await queue.put(make_status_event(...))

# 改为
except Exception as exc:
    if not has_streamed_content:
        await queue.put(make_status_event(...))
    # 已流出的内容无需重发，保持 break
```

#### 1c. tool_calls 路径 — discard 改为已发送日志

```python
# 当前
if finish_reason == "tool_calls":
    if buffered_content:
        logger.info("discarding %d buffered content chunks ...")
    assistant_msg = choice.message.model_dump()
    if buffered_content:
        assistant_msg.pop("content", None)

# 改为
if finish_reason == "tool_calls":
    if has_streamed_content:
        logger.info("intermediate content already streamed ...")
    assistant_msg = choice.message.model_dump()
    if has_streamed_content:
        assistant_msg.pop("content", None)
```

#### 1d. stop 路径 — 移除 flush

```python
# 当前
for event in buffered_content:
    await queue.put(event)
break

# 改为
break  # content 已实时流出
```

#### 1e. 模块级 docstring 更新

```python
# 当前
"""...Runs tool-loop decisions in non-streaming mode until finish_reason == "stop",
then returns final response (non-stream) or streams final output (stream)."""

# 改为
"""...Non-streaming path returns final response object.
Streaming path sends content chunks directly to client in real-time;
if LLM mixes content with tool_calls, the intermediate text is already
visible to the user, and stripped from message history before the next iteration."""
```

### 2. 测试更新

**文件**: `mentor-agent-service/tests/unit/test_agent_service.py`

#### 2a. `test_buffer_discard_content_on_tool_calls` (line 324)

行为变化：中间文字 "Let me search." 不再被 discard，而是直接流给客户端。

```python
# 当前断言
assert "Let me search." not in event_text  # discarded

# 改为
assert "Let me search." in event_text  # streamed directly
```

测试名重命名: `test_intermediate_content_streamed_before_tool_calls`

#### 2b. `test_buffer_multi_step_tools_all_execute` (line 388)

同理：中间文字 "Searching..." 不再 discard。

```python
# 当前断言
assert "Searching..." not in event_text  # discarded

# 改为
assert "Searching..." in event_text  # streamed directly
```

测试名重命名: `test_multi_step_tools_with_intermediate_content_streamed`

#### 2c. `test_buffer_normal_flow_flushes_on_stop` (line 456)

无需改测试逻辑（final answer 仍然可见），但注释/名称微调。

测试名重命名: `test_tool_then_final_answer_streamed`

#### 2d. 新增测试：部分流出 + builder 异常

验证"已流出部分 content + `stream_chunk_builder` 抛异常"时：
- 不发送重复错误状态（`has_streamed_content=True` → 跳过 error status）
- SSE 流正常终止（`[DONE]` event）
- 已流出的内容对客户端仍然可见

```python
async def test_partial_stream_then_builder_error(self, ...):
    """Content partially streamed + stream_chunk_builder fails →
    no duplicate error status, stream terminates cleanly."""
    # Iter 0: stream some content, then builder raises
    async def _stream_with_content():
        yield MockChunk("Partial content here")
        yield MockChunk(None, finish_reason="stop")

    mock_litellm.stream_chunk_builder = MagicMock(
        side_effect=Exception("builder crash")
    )
    ...
    # Already-streamed content visible
    assert "Partial content" in event_text
    # No error status (content was already streamed)
    assert "⚠️" not in event_text
    # Stream terminated
    assert "data: [DONE]" in event_text
```

#### 2e. 新增测试：每轮都有 content 的多迭代场景

验证 3 轮迭代中每轮都有 content + 最终回答：中间文字全部可见，无 double-response 回归。

```python
async def test_multi_iteration_all_with_content(self, ...):
    """3 iterations: each has content + tool_calls, final has content + stop.
    All intermediate content visible, no context pollution."""
    # Iter 0: "Let me check..." + tool_calls
    # Iter 1: "Found something, let me verify..." + tool_calls
    # Iter 2: "Here is the final answer." + stop
    ...
    assert "Let me check" in event_text
    assert "Found something" in event_text
    assert "final answer" in event_text
    assert event_text.count("Running echo") == 2
```

#### 2f. 其他测试不受影响

- `test_no_tool_use_streams_directly` — 无变化
- `test_tool_use_then_stream` — 无变化
- `test_llm_error_returns_error_in_stream` — 无变化

### 3. 不改动的部分

| 组件 | 原因 |
|------|------|
| `sse_generator.py` | SSE 格式不变 |
| `run_agent_loop()` (non-streaming) | 不影响 |
| `llm_service.py` | 不影响 |
| Open WebUI 前端 | 不需要前端改动 |
| tool 函数 | 不影响 |

## 行为 trade-off 分析

| 场景 | 当前行为 | 改后行为 | 影响 |
|------|----------|----------|------|
| 简单问答（无工具） | 一次性弹出 | 逐 token 流式 ✅ | 体验大幅提升 |
| 单工具调用（LLM 无中间文字） | 一次性弹出 | 逐 token 流式 ✅ | 体验大幅提升 |
| 单工具调用（LLM 有中间文字） | 一次性弹出最终回答 | 先看到 "让我查一下..." → 工具状态 → 最终回答 | 用户体验仍OK，类似 ChatGPT |
| 多步工具链 | 只看到最终回答 | 每步中间文字都可见 + 工具状态 → 最终回答 | 更透明，但文字可能略显冗余 |

**关键安全保证保留**：
- `assistant_msg.pop("content", None)` 仍在 tool_calls 路径执行 → 下一轮 LLM 不会看到已流给用户的中间文字 → 不会出现"延续不可见上下文"问题
- `stream_chunk_builder` 仍重建完整响应 → finish_reason 和 tool_calls 检测不受影响

## 与原始 double-response bug 的关系

Buffer+Discard 最初是为了解决 "double-response" 问题而引入的。该问题有两层：

1. **视觉层（cosmetic）**：LLM 在调用工具前输出一段中间文字（如 "让我查一下..."），用户先看到这段文字，再看到工具执行状态，最后看到正式回答。
2. **上下文污染（correctness）**：如果中间文字保留在 message history 中，下一轮 LLM 会看到这段文字并可能从中"续写"，导致回答引用了用户已经看过的内容、逻辑不连贯或重复。

本次改动对这两层的影响：

| 层面 | 改动前（Buffer+Discard） | 改动后（直接流式） | 风险 |
|------|--------------------------|---------------------|------|
| 视觉层 | 中间文字被 discard，用户只看到最终回答 | 中间文字实时可见 → 💭 Thinking → 🔧 Tool → 最终回答 | **预期行为**，类似 ChatGPT tool use 流程 |
| 上下文污染 | `assistant_msg.pop("content", None)` strip content | **同样 strip**，逻辑不变 | **无风险**，下一轮 LLM 仍看不到中间文字 |

结论：原始 double-response bug 的核心问题（上下文污染）**不会复现**。视觉层变化是有意的 trade-off。

## 与 TD-007 的关系

TD-007 描述的 Provisional/Commit 协议（需要 Open WebUI 前端配合）仍是"完美方案"。本次改动是**实用中间方案**：

- 不需要前端改动
- 解决了用户反馈的"无流式输出"痛点
- 唯一 trade-off（中间文字可见）在实际使用中可接受

TD-007 可保留为"未来增强"，降级为 Low severity。

## 变更文件清单

| 文件 | 改动类型 | 行数估算 |
|------|----------|----------|
| `app/services/agent_service.py` | 修改 | ~20 行 |
| `tests/unit/test_agent_service.py` | 修改 + 新增 2 个测试 | ~80 行 |
| `docs/improvement/tech-debt.md` | TD-007 更新 | ~5 行 |
| **合计** | | ~105 行 |
