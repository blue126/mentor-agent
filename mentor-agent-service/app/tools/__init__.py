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
            "Analyze an uploaded book/document and generate a structured learning plan with chapters and sections. "
            "Use this when the user uploads a PDF and asks to create a study plan, learning roadmap, or wants to know "
            "what topics the book covers. The tool searches the knowledge base for the document's table of contents, "
            "extracts the chapter structure using AI, and saves it as a learning plan."
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
                        "Set to true to delete an existing learning plan and regenerate it. "
                        "Use when the previous plan was incorrect or needs updating."
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
            "Retrieve existing learning plans from the knowledge graph. "
            "Use this when the user asks 'What's next?', 'Show my learning plan', "
            "or wants to review their study progress. "
            "Without a topic_name, lists all available plans. "
            "With a topic_name, shows the detailed chapter/section structure."
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
