from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/mentor.db"
    litellm_base_url: str = "http://claude-max-proxy:3456/v1"
    litellm_key: str = ""
    litellm_model: str = "sonnet"
    openwebui_base_url: str = "http://open-webui:8080"
    openwebui_api_key: str = ""
    openwebui_default_collection_names: str = ""
    agent_api_key: str = "your-bearer-token-here"
    notion_token: str = ""
    notion_db_id: str = ""
    anki_connect_url: str = "http://anki:8765"
    system_prompt_path: str = "app/prompts/mentor_system_prompt.md"
    mentor_mode_enabled: bool = True
    max_tool_iterations: int = 10
    sse_heartbeat_interval: int = 15
    port: int = 8100

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
