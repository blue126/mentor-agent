from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/mentor.db"
    litellm_base_url: str = "http://litellm-claude-code:4000/v1"
    litellm_key: str = ""
    openwebui_base_url: str = "http://open-webui:8080"
    openwebui_api_key: str = ""
    agent_api_key: str = ""
    notion_token: str = ""
    notion_db_id: str = ""
    anki_connect_url: str = "http://anki:8765"
    port: int = 8100

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
