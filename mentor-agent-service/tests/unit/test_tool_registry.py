"""Unit tests for tool registry — registration, lookup, schema retrieval, unknown tool handling."""

import pytest

from app.tools.definitions import ToolDefinition
from app.tools.registry import ToolRegistry


async def _dummy_tool(message: str) -> str:
    return f"dummy: {message}"


async def _another_tool(x: int) -> str:
    return str(x * 2)


class TestToolRegistry:
    def test_register_and_get_tool(self):
        reg = ToolRegistry()
        schema = {"description": "A dummy tool", "parameters": {"type": "object", "properties": {}}}
        reg.register("dummy", _dummy_tool, schema)

        assert reg.get_tool("dummy") is _dummy_tool

    def test_get_tool_returns_none_for_unknown(self):
        reg = ToolRegistry()
        assert reg.get_tool("nonexistent") is None

    def test_get_all_schemas_empty(self):
        reg = ToolRegistry()
        assert reg.get_all_schemas() == []

    def test_get_all_schemas_returns_openai_format(self):
        reg = ToolRegistry()
        schema = {
            "description": "Echo tool",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        }
        reg.register("echo", _dummy_tool, schema)

        schemas = reg.get_all_schemas()
        assert len(schemas) == 1
        assert schemas[0]["type"] == "function"
        assert schemas[0]["function"]["name"] == "echo"
        assert schemas[0]["function"]["description"] == "Echo tool"
        assert "parameters" in schemas[0]["function"]

    def test_get_all_schemas_multiple_tools(self):
        reg = ToolRegistry()
        schema1 = {"description": "Tool A", "parameters": {"type": "object", "properties": {}}}
        schema2 = {"description": "Tool B", "parameters": {"type": "object", "properties": {}}}
        reg.register("tool_a", _dummy_tool, schema1)
        reg.register("tool_b", _another_tool, schema2)

        schemas = reg.get_all_schemas()
        assert len(schemas) == 2
        names = {s["function"]["name"] for s in schemas}
        assert names == {"tool_a", "tool_b"}

    def test_list_tools_returns_registered_names(self):
        reg = ToolRegistry()
        schema = {"description": "Tool", "parameters": {"type": "object", "properties": {}}}
        reg.register("alpha", _dummy_tool, schema)
        reg.register("beta", _another_tool, schema)

        names = reg.list_tools()
        assert set(names) == {"alpha", "beta"}

    def test_list_tools_empty(self):
        reg = ToolRegistry()
        assert reg.list_tools() == []

    def test_register_rejects_sync_function(self):
        reg = ToolRegistry()
        schema = {"description": "Bad tool", "parameters": {"type": "object", "properties": {}}}

        def sync_func(message: str) -> str:
            return message

        with pytest.raises(TypeError, match="must be an async function"):
            reg.register("bad", sync_func, schema)


class TestToolDefinition:
    def test_tool_definition_fields(self):
        td = ToolDefinition(
            name="echo",
            description="Echo back the message",
            parameters={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        )
        assert td.name == "echo"
        assert td.description == "Echo back the message"
        assert td.parameters["required"] == ["message"]
