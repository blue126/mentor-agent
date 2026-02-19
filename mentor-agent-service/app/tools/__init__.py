"""Tools package — global registry instance with registered tools."""

from app.tools.echo_tool import echo
from app.tools.registry import ToolRegistry

registry = ToolRegistry()

# Register echo tool
registry.register(
    name="echo",
    func=echo,
    schema={
        "description": "Echo back the given message (test tool)",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message to echo back",
                },
            },
            "required": ["message"],
        },
    },
)
