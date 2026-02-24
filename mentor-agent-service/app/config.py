"""Application configuration — settings and multi-provider routing."""

import logging
from dataclasses import dataclass

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# URL markers indicating direct Anthropic API access (no openai/ prefix needed).
# When base_url points to a proxy (claude-max-proxy, LiteLLM), models need
# the "openai/" prefix so LiteLLM treats them as OpenAI-compatible targets.
# P2: once LITELLM_* naming is neutralised, this sniffing can be simplified.
_DIRECT_API_URL_MARKERS = ("api.anthropic.com",)


def _normalize_model_for_litellm(model: str, base_url: str) -> str:
    """Add 'openai/' prefix when routing through a proxy, skip for direct API."""
    if "/" in model:
        return model

    if any(marker in base_url.lower() for marker in _DIRECT_API_URL_MARKERS):
        return model

    return f"openai/{model}"


@dataclass(frozen=True)
class ProviderConfig:
    """Resolved provider configuration for LLM routing."""

    id: str  # Routing ID visible in Open WebUI (e.g., "mentor-sub")
    display_name: str  # Human-friendly name for UI and SSE events
    base_url: str  # Upstream URL (e.g., "http://claude-max-proxy:3456/v1")
    api_key: str  # Auth credential for upstream
    model: str  # Fully-qualified LiteLLM model name (e.g., "openai/claude-sonnet-4-6")


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/mentor.db"
    litellm_base_url: str = "http://claude-max-proxy:3456/v1"
    litellm_key: str = ""
    litellm_model: str = "sonnet"
    # Primary provider optional overrides
    litellm_provider_id: str = ""
    litellm_display_name: str = ""
    # Secondary provider env vars
    litellm_alt_base_url: str = ""
    litellm_alt_key: str = ""
    litellm_alt_model: str = ""
    litellm_alt_provider_id: str = ""
    litellm_alt_display_name: str = ""

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


def _sanitize_provider_id(raw_id: str) -> str:
    """Ensure provider ID is URL-safe by replacing '/' with '-'."""
    sanitized = raw_id.replace("/", "-")
    if sanitized != raw_id:
        logger.warning("Provider ID sanitized: '%s' → '%s' (must be URL-safe)", raw_id, sanitized)
    return sanitized


def get_providers() -> list[ProviderConfig]:
    """Build provider list from env vars. Always at least one (primary)."""
    primary_model = _normalize_model_for_litellm(
        settings.litellm_model,
        settings.litellm_base_url,
    )
    raw_primary_id = settings.litellm_provider_id or settings.litellm_model.replace("/", "-")
    primary_id = _sanitize_provider_id(raw_primary_id)
    primary = ProviderConfig(
        id=primary_id,
        display_name=settings.litellm_display_name or primary_id,
        base_url=settings.litellm_base_url,
        api_key=settings.litellm_key,
        model=primary_model,
    )
    providers = [primary]

    if settings.litellm_alt_base_url:
        # Validate minimum required fields for secondary provider
        missing_fields = []
        if not settings.litellm_alt_model:
            missing_fields.append("LITELLM_ALT_MODEL")
        if missing_fields:
            logger.warning(
                "Secondary provider skipped — missing required fields: %s",
                ", ".join(missing_fields),
            )
            return providers

        alt_model = _normalize_model_for_litellm(
            settings.litellm_alt_model,
            settings.litellm_alt_base_url,
        )
        raw_alt_id = settings.litellm_alt_provider_id or settings.litellm_alt_model.replace("/", "-")
        alt_id = _sanitize_provider_id(raw_alt_id)
        alt = ProviderConfig(
            id=alt_id,
            display_name=settings.litellm_alt_display_name or alt_id,
            base_url=settings.litellm_alt_base_url,
            api_key=settings.litellm_alt_key,
            model=alt_model,
        )
        providers.append(alt)

    return providers


def resolve_provider(model_id: str | None) -> ProviderConfig | None:
    """Resolve a model ID to a ProviderConfig.

    - None/empty → primary provider (backwards compat)
    - Matches provider ID (case-insensitive) → that provider
    - Explicit but unknown → None (caller decides error handling)
    """
    providers = get_providers()

    if not model_id:
        return providers[0]

    model_id_lower = model_id.lower()
    for provider in providers:
        if provider.id.lower() == model_id_lower:
            return provider

    return None
