"""Agent service — Tool Use loop orchestrator.

Calls llm_service for LLM interaction and tool registry for tool dispatch.
Runs tool-loop decisions in non-streaming mode until finish_reason == "stop",
then returns final response (non-stream) or streams final output (stream).
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import litellm

from app.config import settings
from app.services import llm_service, prompt_service
from app.tools import registry
from app.utils.sse_generator import (
    make_done_event,
    make_status_event,
    queue_sse_stream,
    run_heartbeat,
)

logger = logging.getLogger(__name__)


async def _inject_system_prompt(messages: list[dict[str, Any]]) -> None:
    """Prepend or replace the system prompt at position 0 of messages."""
    system_content = await prompt_service.load_system_prompt()
    system_msg = {"role": "system", "content": system_content}

    if messages and messages[0].get("role") == "system":
        messages[0] = system_msg
    else:
        messages.insert(0, system_msg)


# Common LLM parameter name aliases → canonical schema names.
# LLMs sometimes use intuitive but non-schema param names; this map
# rescues those calls instead of silently dropping the arguments.
_PARAM_ALIASES: dict[str, str] = {
    "topic_name": "source_name",
    "book_name": "source_name",
    "knowledge_base_id": "collection_name",
    "kb_id": "collection_name",
}


async def _execute_tool(fn_name: str, fn_args_raw: str) -> str:
    """Execute a single tool call with Fail Soft error handling."""
    # Parse arguments (Fail Soft on malformed JSON)
    try:
        fn_args = json.loads(fn_args_raw)
    except (json.JSONDecodeError, TypeError) as exc:
        return f"Error: Failed to parse arguments for '{fn_name}': {exc}. Hint: arguments must be valid JSON"

    # Lookup tool
    tool_func = registry.get_tool(fn_name)
    if tool_func is None:
        available = ", ".join(registry.list_tools())
        return f"Error: Unknown tool '{fn_name}'. Available tools: [{available}]"

    # Filter args to schema-defined parameters only (prevent LLM-hallucinated params
    # from reaching the function and bypassing auto-discover / default logic).
    # Also applies alias mapping: if LLM uses a known alias (e.g. "topic_name")
    # for a schema param (e.g. "source_name"), remap instead of dropping.
    tool_schema = registry.get_schema(fn_name)
    schema_params: set[str] | None = None
    if isinstance(tool_schema, dict):
        props = tool_schema.get("parameters", {})
        if isinstance(props, dict):
            prop_keys = props.get("properties", {})
            if isinstance(prop_keys, dict) and prop_keys:
                schema_params = set(prop_keys.keys())
    if schema_params is not None:
        resolved: dict[str, Any] = {}
        for k, v in fn_args.items():
            if k in schema_params:
                resolved[k] = v
            elif k in _PARAM_ALIASES:
                canonical = _PARAM_ALIASES[k]
                if canonical in schema_params and canonical not in resolved and canonical not in fn_args:
                    logger.info("_execute_tool alias: %s → %s for tool %s", k, canonical, fn_name)
                    resolved[canonical] = v
        fn_args = resolved

    # Execute tool (Fail Soft on exceptions)
    try:
        result = await tool_func(**fn_args)
        return str(result) if not isinstance(result, str) else result
    except TypeError as exc:
        # Return schema-defined params (not function signature) to guide LLM self-correction
        expected = list(schema_params) if schema_params else []
        return (
            f"Error: {fn_name} parameter error: {exc}. "
            f"Expected parameters: {expected}. "
            f"Hint: Retry with correct parameter names."
        )
    except Exception as exc:
        return f"Error: {fn_name} failed: {exc}. Hint: Check input parameters and try again."


async def run_agent_loop(
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Any | str:
    """Non-streaming agent loop. Returns final LLM response object or error string."""
    await _inject_system_prompt(messages)
    tools = registry.get_all_schemas()
    max_iterations = settings.max_tool_iterations

    for iteration in range(max_iterations):
        logger.info("tool-loop(non-stream) iteration=%s", iteration + 1)
        result = await llm_service.get_chat_completion_with_tools(
            messages=messages,
            tools=tools,
            tool_choice="auto",
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # Fail Soft: LLM error
        if isinstance(result, str):
            return result

        # Fail Soft: empty choices
        if not getattr(result, "choices", None):
            return "Error: LLM returned empty choices"

        choice = result.choices[0]
        finish_reason = choice.finish_reason
        logger.info("tool-loop(non-stream) finish_reason=%s", finish_reason)

        if finish_reason == "tool_calls" and getattr(choice.message, "tool_calls", None):
            # Append assistant message (with tool_calls) to conversation
            messages.append(choice.message.model_dump())

            # Execute each tool call
            for tool_call in choice.message.tool_calls:
                logger.info(
                    "tool-loop(non-stream) calling tool name=%s args=%s",
                    tool_call.function.name,
                    tool_call.function.arguments,
                )
                tool_result = await _execute_tool(
                    fn_name=tool_call.function.name,
                    fn_args_raw=tool_call.function.arguments,
                )
                logger.info(
                    "tool-loop(non-stream) tool_result name=%s result=%s",
                    tool_call.function.name,
                    tool_result[:200],
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": tool_result,
                })
        else:
            # finish_reason == "stop" or no tool_calls — return final response
            return result

    # Max iterations reached
    return f"Error: Tool use loop reached maximum iterations ({max_iterations}). The assistant may be stuck in a loop."


async def run_agent_loop_streaming(
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """Streaming agent loop with SSE status updates.

    Returns an AsyncIterator[str] that yields formatted SSE events:
    status events, content deltas, and [DONE] terminator.
    """
    await _inject_system_prompt(messages)
    resolved_model = model or settings.litellm_model
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    done = asyncio.Event()

    async def _agent_loop() -> None:
        try:
            tools = registry.get_all_schemas()
            iteration = 0

            while iteration < settings.max_tool_iterations:
                logger.info("tool-loop(stream) iteration=%s", iteration + 1)

                # Always stream with tools — let LLM decide whether to use them
                stream_result = await llm_service.stream_chat_completion(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                    tool_choice="auto",
                )
                if isinstance(stream_result, str):
                    await queue.put(make_status_event(f"⚠️ {stream_result}", resolved_model))
                    break

                # Buffer content chunks — only flush on finish_reason="stop".
                # This prevents "double-response" when LLM mixes content +
                # tool_calls: content is discarded, tools execute, and only
                # the final answer (after all tools complete) reaches the client.
                chunks: list[Any] = []
                buffered_content: list[str] = []
                async for chunk in stream_result:
                    chunks.append(chunk)
                    chunk_dict = chunk.model_dump(exclude_none=True)
                    choices = chunk_dict.get("choices", [])
                    if choices and choices[0].get("delta", {}).get("content"):
                        buffered_content.append(f"data: {json.dumps(chunk_dict)}\n\n")

                # Rebuild complete response to inspect finish_reason / tool_calls
                try:
                    rebuilt = litellm.stream_chunk_builder(chunks, messages=messages)
                except Exception as exc:
                    logger.exception("stream_chunk_builder failed: %s", exc)
                    if buffered_content:
                        # Flush what we have — it's the best response available.
                        for event in buffered_content:
                            await queue.put(event)
                    else:
                        await queue.put(make_status_event(f"⚠️ Error: {exc}", resolved_model))
                    break

                if not getattr(rebuilt, "choices", None):
                    await queue.put(make_status_event("⚠️ Error: LLM returned empty choices", resolved_model))
                    break

                choice = rebuilt.choices[0]
                finish_reason = choice.finish_reason
                logger.info("tool-loop(stream) finish_reason=%s", finish_reason)

                if finish_reason == "tool_calls" and getattr(choice.message, "tool_calls", None):
                    # Discard any buffered content — LLM mixed text + tool_calls.
                    if buffered_content:
                        logger.info(
                            "tool-loop(stream) discarding %d buffered content "
                            "chunks (finish_reason=tool_calls, iteration=%s)",
                            len(buffered_content),
                            iteration + 1,
                        )

                    await queue.put(make_status_event("💭 Thinking...", resolved_model))
                    # Append assistant message but strip discarded content so the
                    # next LLM call doesn't see text the user never received.
                    # This prevents "continuation" responses that reference invisible context.
                    assistant_msg = choice.message.model_dump()
                    if buffered_content:
                        assistant_msg.pop("content", None)
                    messages.append(assistant_msg)

                    for tool_call in choice.message.tool_calls:
                        fn_name = tool_call.function.name
                        logger.info(
                            "tool-loop(stream) calling tool name=%s args=%s",
                            fn_name,
                            tool_call.function.arguments,
                        )
                        await queue.put(make_status_event(f"🔧 Running {fn_name}...", resolved_model))
                        tool_result = await _execute_tool(fn_name, tool_call.function.arguments)
                        logger.info(
                            "tool-loop(stream) tool_result name=%s result=%s",
                            fn_name,
                            tool_result[:200],
                        )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": fn_name,
                            "content": tool_result,
                        })
                    iteration += 1
                    continue

                # finish_reason == "stop" — flush buffered content to client.
                for event in buffered_content:
                    await queue.put(event)
                break
            else:
                # Max iterations reached
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

    agent_task = asyncio.create_task(_agent_loop())
    heartbeat_task = asyncio.create_task(
        run_heartbeat(queue, done, settings.sse_heartbeat_interval),
    )

    try:
        async for event in queue_sse_stream(queue):
            yield event
    finally:
        done.set()
        for task in (agent_task, heartbeat_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(agent_task, heartbeat_task, return_exceptions=True)
