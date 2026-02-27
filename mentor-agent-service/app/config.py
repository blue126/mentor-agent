"""Application configuration — settings and multi-provider routing.

Provider configuration is loaded exclusively from providers.yaml.
Legacy LITELLM_* environment variables are no longer supported.
"""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# URL markers indicating direct API access (no openai/ prefix needed).
# When base_url points to a proxy (unified-proxy, etc.),
# models need the "openai/" prefix so LiteLLM treats them as OpenAI-compatible.
_DIRECT_API_URL_MARKERS = ("api.anthropic.com",)

_REQUIRED_PROVIDER_FIELDS = ("id", "display_name", "base_url", "api_key", "model")

# Pattern for ${ENV_VAR} references in YAML values
_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


class ConfigurationError(Exception):
    """Raised when provider configuration is invalid or missing."""


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

    id: str  # Routing ID visible in Open WebUI (e.g., "claude-sub")
    display_name: str  # Human-friendly name for UI and SSE events
    base_url: str  # Upstream URL (e.g., "http://unified-proxy:3456/v1")
    api_key: str  # Auth credential for upstream
    model: str  # Fully-qualified LiteLLM model name (e.g., "openai/claude-sonnet-4-6")
    tool_loop_required: bool = True  # Whether this provider requires tool loop


def _sanitize_provider_id(raw_id: str) -> str:
    """Ensure provider ID is URL-safe by replacing '/' with '-'."""
    sanitized = raw_id.replace("/", "-")
    if sanitized != raw_id:
        logger.warning("Provider ID sanitized: '%s' → '%s' (must be URL-safe)", raw_id, sanitized)
    return sanitized


def _expand_env_vars(value: str) -> str | None:
    """Expand ${ENV_VAR} references in a string value.

    Returns None if a referenced env var is not set.
    """
    missing: list[str] = []

    def _replacer(match: re.Match) -> str:
        var_name = match.group(1)
        env_val = os.environ.get(var_name)
        if env_val is None:
            missing.append(var_name)
            return match.group(0)  # keep original for error reporting
        return env_val

    result = _ENV_VAR_PATTERN.sub(_replacer, value)
    if missing:
        return None
    return result


def _validate_base_url(url: str) -> bool:
    """Check that base_url starts with http:// or https://."""
    return url.startswith("http://") or url.startswith("https://")


def load_providers_from_yaml(yaml_path: str | Path) -> list[ProviderConfig]:
    """Parse providers.yaml and build validated ProviderConfig list.

    Invalid providers are logged (WARNING) and skipped.
    Raises ConfigurationError if file is missing, malformed, or yields zero valid providers.
    """
    path = Path(yaml_path)
    if not path.is_file():
        raise ConfigurationError(
            f"Provider configuration file not found: {path}. "
            "Create a providers.yaml file or set PROVIDERS_YAML_PATH env var."
        )

    try:
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML format in {path}: {exc}") from exc

    if not isinstance(data, dict) or "providers" not in data:
        raise ConfigurationError(
            f"Invalid providers.yaml format in {path}: "
            "expected top-level 'providers' key with a list of provider entries."
        )

    raw_providers = data["providers"]
    if not isinstance(raw_providers, list):
        raise ConfigurationError(
            f"Invalid providers.yaml format in {path}: "
            "'providers' must be a list."
        )

    providers: list[ProviderConfig] = []

    for idx, entry in enumerate(raw_providers):
        if not isinstance(entry, dict):
            logger.warning("Skipped provider at index %d: not a dict", idx)
            continue

        # Check required fields
        missing = [f for f in _REQUIRED_PROVIDER_FIELDS if not entry.get(f)]
        if missing:
            provider_id = entry.get("id", f"<index {idx}>")
            logger.warning(
                "Skipped provider '%s' (missing required field: %s)",
                provider_id,
                ", ".join(missing),
            )
            continue

        # Validate base_url format
        base_url = str(entry["base_url"])
        if not _validate_base_url(base_url):
            logger.warning(
                "Skipped provider '%s' (invalid base_url: %s — must start with http:// or https://)",
                entry["id"],
                base_url,
            )
            continue

        # Expand env vars in api_key
        raw_api_key = str(entry["api_key"])
        if _ENV_VAR_PATTERN.search(raw_api_key):
            expanded = _expand_env_vars(raw_api_key)
            if expanded is None:
                logger.warning(
                    "Skipped provider '%s' (unresolved env var in api_key: %s)",
                    entry["id"],
                    raw_api_key,
                )
                continue
            api_key = expanded
        else:
            api_key = raw_api_key

        # Sanitize provider ID
        provider_id = _sanitize_provider_id(str(entry["id"]))

        # Normalize model for LiteLLM
        raw_model = str(entry["model"])
        normalized_model = _normalize_model_for_litellm(raw_model, base_url)
        if normalized_model != raw_model:
            logger.debug(
                "Normalized model for %s: %s → %s",
                provider_id,
                raw_model,
                normalized_model,
            )

        provider = ProviderConfig(
            id=provider_id,
            display_name=str(entry["display_name"]),
            base_url=base_url,
            api_key=api_key,
            model=normalized_model,
        )
        providers.append(provider)

    if not providers:
        raise ConfigurationError(
            f"No valid provider found in {path}. "
            "Check providers.yaml for missing required fields or invalid configuration."
        )

    logger.info(
        "Successfully loaded %d providers: %s",
        len(providers),
        [p.id for p in providers],
    )
    return providers


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/mentor.db"
    providers_yaml_path: str = ""

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

# Module-level cache for providers (loaded once, reused)
_providers_cache: list[ProviderConfig] | None = None


def get_providers() -> list[ProviderConfig]:
    """Load providers from YAML configuration (cached after first call).

    Loading priority:
    1. PROVIDERS_YAML_PATH env var → load that file
    2. ./providers.yaml (default location)
    3. Neither exists → raise ConfigurationError

    Raises ConfigurationError if no valid configuration is found.
    """
    global _providers_cache  # noqa: PLW0603
    if _providers_cache is not None:
        return _providers_cache

    # Step 1: Check PROVIDERS_YAML_PATH env var
    yaml_path = settings.providers_yaml_path
    if yaml_path:
        logger.info("Provider configuration: Loading from PROVIDERS_YAML_PATH=%s", yaml_path)
        _providers_cache = load_providers_from_yaml(yaml_path)
        return _providers_cache

    # Step 2: Try default location ./providers.yaml
    default_path = Path("./providers.yaml")
    if default_path.is_file():
        logger.info("Provider configuration: Loading from %s", default_path)
        _providers_cache = load_providers_from_yaml(default_path)
        return _providers_cache

    # Step 3: No configuration found
    raise ConfigurationError(
        "Provider configuration file not found. "
        "Create providers.yaml in the project root or set PROVIDERS_YAML_PATH env var. "
        "See providers.yaml.example for format reference."
    )


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


def reset_providers_cache() -> None:
    """Reset the cached providers list. Used in testing."""
    global _providers_cache  # noqa: PLW0603
    _providers_cache = None
