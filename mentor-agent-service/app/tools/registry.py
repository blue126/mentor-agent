"""Tool registry — dynamic name→function+schema mapping for agent tool dispatch."""

import inspect
from typing import Any, Callable, Coroutine


class ToolRegistry:
    """Register async tool functions with their OpenAI-compatible schemas."""

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Coroutine[Any, Any, str]]] = {}
        self._schemas: dict[str, dict[str, Any]] = {}

    def register(self, name: str, func: Callable[..., Coroutine[Any, Any, str]], schema: dict[str, Any]) -> None:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"Tool '{name}' must be an async function, got {type(func).__name__}")
        self._tools[name] = func
        self._schemas[name] = schema

    def get_tool(self, name: str) -> Callable[..., Coroutine[Any, Any, str]] | None:
        return self._tools.get(name)

    def get_schema(self, name: str) -> dict[str, Any] | None:
        return self._schemas.get(name)

    def get_all_schemas(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": n, **s}}
            for n, s in self._schemas.items()
        ]

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())
