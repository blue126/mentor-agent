"""Tool definition types for the tool registry."""

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolDefinition:
    """Schema definition for a registered tool (OpenAI tool spec compatible)."""

    name: str
    description: str
    parameters: dict[str, Any]
