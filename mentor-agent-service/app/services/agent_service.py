"""Agent service — Tool Use loop orchestrator.

Calls llm_service for LLM interaction and tool registry for tool dispatch.
Runs tool-loop decisions in non-streaming mode until finish_reason == "stop",
then returns final response (non-stream) or streams final output (stream).
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from app.config import settings
from app.services import llm_service
from app.tools import registry


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

    # Execute tool (Fail Soft on exceptions)
    try:
        result = await tool_func(**fn_args)
        return str(result) if not isinstance(result, str) else result
    except Exception as exc:
        return f"Error: {fn_name} failed: {exc}. Hint: Check input parameters and try again."


async def run_agent_loop(
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Any | str:
    """Non-streaming agent loop. Returns final LLM response object or error string."""
    tools = registry.get_all_schemas()
    max_iterations = settings.max_tool_iterations

    for iteration in range(max_iterations):
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

        if finish_reason == "tool_calls" and getattr(choice.message, "tool_calls", None):
            # Append assistant message (with tool_calls) to conversation
            messages.append(choice.message.model_dump())

            # Execute each tool call
            for tool_call in choice.message.tool_calls:
                tool_result = await _execute_tool(
                    fn_name=tool_call.function.name,
                    fn_args_raw=tool_call.function.arguments,
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
) -> AsyncIterator[Any] | str:
    """Streaming agent loop. Returns LLM stream iterator or error string."""
    tools = registry.get_all_schemas()
    max_iterations = settings.max_tool_iterations

    for _ in range(max_iterations):
        result = await llm_service.get_chat_completion_with_tools(
            messages=messages,
            tools=tools,
            tool_choice="auto",
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if isinstance(result, str):
            return result

        if not getattr(result, "choices", None):
            return "Error: LLM returned empty choices"

        choice = result.choices[0]
        finish_reason = choice.finish_reason

        if finish_reason == "tool_calls" and getattr(choice.message, "tool_calls", None):
            messages.append(choice.message.model_dump())
            for tool_call in choice.message.tool_calls:
                tool_result = await _execute_tool(
                    fn_name=tool_call.function.name,
                    fn_args_raw=tool_call.function.arguments,
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": tool_result,
                })
            continue

        return await llm_service.stream_chat_completion(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    return f"Error: Tool use loop reached maximum iterations ({max_iterations}). The assistant may be stuck in a loop."
