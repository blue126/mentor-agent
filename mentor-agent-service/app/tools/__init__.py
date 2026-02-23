"""Tools package — global registry instance with registered tools."""

from app.tools.echo_tool import echo
from app.tools.extract_relationships_tool import extract_concept_relationships
from app.tools.learning_plan_tool import generate_learning_plan, get_learning_plan
from app.tools.registry import ToolRegistry
from app.tools.search_knowledge_base_tool import list_collections, search_knowledge_base

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
                    "description": (
                        "The search query to find relevant content in the knowledge base. "
                        "IMPORTANT: Always formulate queries in English, even if the user "
                        "writes in another language, because the embedding model is English-optimized. "
                        "Query strategy: Use specific, descriptive phrases rather than short keywords. "
                        "For example, instead of 'list comprehension', use "
                        "'list comprehension syntax and usage in Python chapter 4'. "
                        "If the first search returns irrelevant results, try rephrasing with "
                        "more context (e.g., include chapter names, section titles, or synonyms)."
                    ),
                },
                "collection_name": {
                    "type": "string",
                    "description": (
                        "Optional: the name of the knowledge base to search (e.g. 'AI-Assisted Programming'). "
                        "Use list_collections to see available names. "
                        "If not provided, searches all knowledge bases."
                    ),
                },
                "k": {
                    "type": "integer",
                    "description": "Number of top results to return (default: 8)",
                    "default": 8,
                },
            },
            "required": ["query"],
        },
    },
)

# Register list_collections tool
registry.register(
    name="list_collections",
    func=list_collections,
    schema={
        "description": (
            "List all available collections and their documents. "
            "Returns collection names with document filenames."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
)

# Register generate_learning_plan tool
registry.register(
    name="generate_learning_plan",
    func=generate_learning_plan,
    schema={
        "description": (
            "CREATE a NEW learning plan from an uploaded book/document. "
            "ONLY use this when the user explicitly asks to CREATE or GENERATE a plan "
            "(e.g., '帮我生成学习计划', 'create a study plan'). "
            "To VIEW an existing plan, use get_learning_plan instead — NEVER use this tool for viewing. "
            "WARNING: with force=true, this PERMANENTLY DELETES the existing plan and regenerates from scratch."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source_name": {
                    "type": "string",
                    "description": "The name of the book or document to create a learning plan for",
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Optional custom search query to find the document's table of contents. "
                        "If not provided, a default query targeting the TOC will be used."
                    ),
                },
                "collection_name": {
                    "type": "string",
                    "description": (
                        "The name of the knowledge base to use (e.g. 'AI-Assisted Programming'). "
                        "Use list_collections to find available collection names."
                    ),
                },
                "force": {
                    "type": "boolean",
                    "description": (
                        "DANGEROUS: Set to true to PERMANENTLY DELETE the existing plan and regenerate from scratch. "
                        "ONLY use when the user EXPLICITLY requests regeneration (e.g., '重新生成', 'regenerate'). "
                        "Never set force=true on your own initiative."
                    ),
                    "default": False,
                },
            },
            "required": ["source_name", "collection_name"],
        },
    },
)

# Register get_learning_plan tool
registry.register(
    name="get_learning_plan",
    func=get_learning_plan,
    schema={
        "description": (
            "VIEW existing learning plans. This is the PRIMARY tool for all plan-related queries. "
            "Use this when the user asks to see, show, review, or check their learning plan. "
            "Without topic_name: lists all available plans with concept counts. "
            "With topic_name: shows the detailed chapter/section structure for that plan. "
            "Always try this tool FIRST before considering generate_learning_plan."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic_name": {
                    "type": "string",
                    "description": (
                        "Optional name of the specific learning plan (book/document) to retrieve. "
                        "If omitted, returns an overview of all learning plans."
                    ),
                },
            },
            "required": [],
        },
    },
)

# Register extract_concept_relationships tool
registry.register(
    name="extract_concept_relationships",
    func=extract_concept_relationships,
    schema={
        "description": (
            "Analyze concepts within a topic and discover prerequisite and related relationships between them. "
            "Use this after generating a learning plan to build the knowledge graph with meaningful connections. "
            "The tool loads all concepts for the given topic, uses AI to identify relationships, "
            "and stores them in the knowledge graph for prerequisite checking and cross-linking."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic_name": {
                    "type": "string",
                    "description": "The name of the topic whose concepts should be analyzed for relationships",
                },
            },
            "required": ["topic_name"],
        },
    },
)
