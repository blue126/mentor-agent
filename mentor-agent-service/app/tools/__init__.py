"""Tools package — global registry instance with registered tools."""

from app.tools.echo_tool import echo
from app.tools.registry import ToolRegistry
from app.tools.search_knowledge_base_tool import list_knowledge_bases, search_knowledge_base

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

# Register search_knowledge_base tool
registry.register(
    name="search_knowledge_base",
    func=search_knowledge_base,
    schema={
        "description": (
            "Search the user's uploaded documents (PDF books) in the knowledge base. "
            "Returns relevant text passages with source attribution. "
            "Use this tool when the user asks about content from their learning materials."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find relevant content in the knowledge base",
                },
                "collection_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Specific knowledge collection IDs to search. Required by upstream API — "
                        "if omitted, the tool will use OPENWEBUI_DEFAULT_COLLECTION_NAMES from config; "
                        "if that is also empty, returns an error prompting the LLM to call "
                        "list_knowledge_bases first."
                    ),
                },
                "k": {
                    "type": "integer",
                    "description": "Number of top results to return",
                    "default": 4,
                },
            },
            "required": ["query"],
        },
    },
)

# Register list_knowledge_bases tool
registry.register(
    name="list_knowledge_bases",
    func=list_knowledge_bases,
    schema={
        "description": (
            "List all available knowledge bases (uploaded document collections). "
            "Use this to discover which collections are available before searching."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
)
