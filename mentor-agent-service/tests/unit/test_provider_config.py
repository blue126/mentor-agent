"""Unit tests for ProviderConfig, get_providers(), and resolve_provider()."""

from unittest.mock import patch

from app.config import (
    ProviderConfig,
    _normalize_model_for_litellm,
    _sanitize_provider_id,
    get_providers,
    resolve_provider,
)

# ---------------------------------------------------------------------------
# _normalize_model_for_litellm tests
# ---------------------------------------------------------------------------

def test_normalize_proxy_url_adds_openai_prefix():
    """Proxy URL → model gets 'openai/' prefix."""
    result = _normalize_model_for_litellm("sonnet", "http://claude-max-proxy:3456/v1")
    assert result == "openai/sonnet"


def test_normalize_direct_api_no_prefix():
    """Direct Anthropic API URL → model has no prefix."""
    result = _normalize_model_for_litellm("claude-sonnet-4-6", "https://api.anthropic.com")
    assert result == "claude-sonnet-4-6"


def test_normalize_model_already_has_slash_passthrough():
    """Model already has '/' → no prefix added (passthrough)."""
    result = _normalize_model_for_litellm("openai/claude-sonnet-4-6", "http://some-proxy:3456/v1")
    assert result == "openai/claude-sonnet-4-6"


def test_normalize_case_insensitive_url_match():
    """URL marker matching should be case-insensitive."""
    result = _normalize_model_for_litellm("claude-sonnet-4-6", "https://API.ANTHROPIC.COM")
    assert result == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# _sanitize_provider_id tests
# ---------------------------------------------------------------------------

def test_sanitize_provider_id_replaces_slash_with_dash():
    """Provider ID containing '/' → sanitized to '-'."""
    assert _sanitize_provider_id("openai/claude-sonnet-4-6") == "openai-claude-sonnet-4-6"


def test_sanitize_provider_id_no_change_when_clean():
    """Clean provider ID → no change."""
    assert _sanitize_provider_id("mentor-sub") == "mentor-sub"


def test_sanitize_provider_id_logs_warning():
    """Sanitization should log a warning when ID is modified."""
    with patch("app.config.logger") as mock_logger:
        _sanitize_provider_id("openai/model")
    mock_logger.warning.assert_called_once()
    assert "sanitized" in mock_logger.warning.call_args[0][0].lower()


# ---------------------------------------------------------------------------
# get_providers() tests — single provider
# ---------------------------------------------------------------------------

@patch("app.config.settings")
def test_get_providers_single_provider_default(mock_settings):
    """No alt config → get_providers() returns single primary provider."""
    mock_settings.litellm_model = "sonnet"
    mock_settings.litellm_base_url = "http://claude-max-proxy:3456/v1"
    mock_settings.litellm_key = "sk-dev"
    mock_settings.litellm_provider_id = ""
    mock_settings.litellm_display_name = ""
    mock_settings.litellm_alt_base_url = ""

    providers = get_providers()
    assert len(providers) == 1
    assert providers[0].id == "sonnet"
    assert providers[0].display_name == "sonnet"
    assert providers[0].model == "openai/sonnet"
    assert providers[0].base_url == "http://claude-max-proxy:3456/v1"
    assert providers[0].api_key == "sk-dev"


@patch("app.config.settings")
def test_get_providers_single_provider_with_custom_id(mock_settings):
    """Primary with custom ID/display name."""
    mock_settings.litellm_model = "sonnet"
    mock_settings.litellm_base_url = "http://claude-max-proxy:3456/v1"
    mock_settings.litellm_key = "sk-dev"
    mock_settings.litellm_provider_id = "mentor-sub"
    mock_settings.litellm_display_name = "Mentor (Subscription)"
    mock_settings.litellm_alt_base_url = ""

    providers = get_providers()
    assert len(providers) == 1
    assert providers[0].id == "mentor-sub"
    assert providers[0].display_name == "Mentor (Subscription)"


# ---------------------------------------------------------------------------
# get_providers() tests — double active
# ---------------------------------------------------------------------------

@patch("app.config.settings")
def test_get_providers_double_active(mock_settings):
    """Both providers configured → get_providers() returns 2 providers."""
    mock_settings.litellm_model = "sonnet"
    mock_settings.litellm_base_url = "http://claude-max-proxy:3456/v1"
    mock_settings.litellm_key = "sk-dev"
    mock_settings.litellm_provider_id = "mentor-sub"
    mock_settings.litellm_display_name = "Mentor (Subscription)"
    mock_settings.litellm_alt_base_url = "https://api.anthropic.com"
    mock_settings.litellm_alt_key = "sk-ant-xxx"
    mock_settings.litellm_alt_model = "claude-sonnet-4-6"
    mock_settings.litellm_alt_provider_id = "mentor-api"
    mock_settings.litellm_alt_display_name = "Mentor (API)"

    providers = get_providers()
    assert len(providers) == 2

    primary = providers[0]
    assert primary.id == "mentor-sub"
    assert primary.display_name == "Mentor (Subscription)"
    assert primary.model == "openai/sonnet"  # proxy → openai/ prefix

    alt = providers[1]
    assert alt.id == "mentor-api"
    assert alt.display_name == "Mentor (API)"
    assert alt.model == "claude-sonnet-4-6"  # direct API → no prefix
    assert alt.base_url == "https://api.anthropic.com"
    assert alt.api_key == "sk-ant-xxx"


@patch("app.config.settings")
def test_get_providers_alt_defaults_id_from_model(mock_settings):
    """Alt provider with no explicit ID → derives from model (slash → dash)."""
    mock_settings.litellm_model = "sonnet"
    mock_settings.litellm_base_url = "http://proxy:3456/v1"
    mock_settings.litellm_key = "sk-dev"
    mock_settings.litellm_provider_id = ""
    mock_settings.litellm_display_name = ""
    mock_settings.litellm_alt_base_url = "https://api.anthropic.com"
    mock_settings.litellm_alt_key = "sk-ant"
    mock_settings.litellm_alt_model = "claude-sonnet-4-6"
    mock_settings.litellm_alt_provider_id = ""
    mock_settings.litellm_alt_display_name = ""

    providers = get_providers()
    assert len(providers) == 2
    alt = providers[1]
    assert alt.id == "claude-sonnet-4-6"
    assert alt.display_name == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# get_providers() tests — validation / skip secondary
# ---------------------------------------------------------------------------

@patch("app.config.logger")
@patch("app.config.settings")
def test_get_providers_skips_alt_missing_model(mock_settings, mock_logger):
    """Alt base_url set but alt_model empty → skips secondary, logs warning."""
    mock_settings.litellm_model = "sonnet"
    mock_settings.litellm_base_url = "http://proxy:3456/v1"
    mock_settings.litellm_key = "sk-dev"
    mock_settings.litellm_provider_id = ""
    mock_settings.litellm_display_name = ""
    mock_settings.litellm_alt_base_url = "https://api.anthropic.com"
    mock_settings.litellm_alt_key = "sk-ant"
    mock_settings.litellm_alt_model = ""  # MISSING
    mock_settings.litellm_alt_provider_id = ""
    mock_settings.litellm_alt_display_name = ""

    providers = get_providers()

    assert len(providers) == 1
    mock_logger.warning.assert_called_once()
    assert "LITELLM_ALT_MODEL" in str(mock_logger.warning.call_args)


# ---------------------------------------------------------------------------
# get_providers() — provider ID derivation sanitises '/' to '-'
# ---------------------------------------------------------------------------

@patch("app.config.settings")
def test_get_providers_primary_id_sanitizes_slash(mock_settings):
    """Primary model 'openai/sonnet' with no explicit ID → derived ID has no slash."""
    mock_settings.litellm_model = "openai/sonnet"
    mock_settings.litellm_base_url = "http://proxy:3456/v1"
    mock_settings.litellm_key = "sk-dev"
    mock_settings.litellm_provider_id = ""
    mock_settings.litellm_display_name = ""
    mock_settings.litellm_alt_base_url = ""

    providers = get_providers()
    assert providers[0].id == "openai-sonnet"
    assert "/" not in providers[0].id


# ---------------------------------------------------------------------------
# resolve_provider() tests
# ---------------------------------------------------------------------------

@patch("app.config.settings")
def test_resolve_provider_none_returns_primary(mock_settings):
    """None model_id → returns primary provider (backwards compat)."""
    mock_settings.litellm_model = "sonnet"
    mock_settings.litellm_base_url = "http://proxy:3456/v1"
    mock_settings.litellm_key = "sk-dev"
    mock_settings.litellm_provider_id = "mentor-sub"
    mock_settings.litellm_display_name = "Mentor (Sub)"
    mock_settings.litellm_alt_base_url = ""

    provider = resolve_provider(None)
    assert provider is not None
    assert provider.id == "mentor-sub"


@patch("app.config.settings")
def test_resolve_provider_empty_string_returns_primary(mock_settings):
    """Empty string model_id → returns primary provider."""
    mock_settings.litellm_model = "sonnet"
    mock_settings.litellm_base_url = "http://proxy:3456/v1"
    mock_settings.litellm_key = "sk-dev"
    mock_settings.litellm_provider_id = "mentor-sub"
    mock_settings.litellm_display_name = "Mentor (Sub)"
    mock_settings.litellm_alt_base_url = ""

    provider = resolve_provider("")
    assert provider is not None
    assert provider.id == "mentor-sub"


@patch("app.config.settings")
def test_resolve_provider_matches_by_id(mock_settings):
    """Exact ID match → returns that provider."""
    mock_settings.litellm_model = "sonnet"
    mock_settings.litellm_base_url = "http://proxy:3456/v1"
    mock_settings.litellm_key = "sk-dev"
    mock_settings.litellm_provider_id = "mentor-sub"
    mock_settings.litellm_display_name = "Mentor (Sub)"
    mock_settings.litellm_alt_base_url = "https://api.anthropic.com"
    mock_settings.litellm_alt_key = "sk-ant"
    mock_settings.litellm_alt_model = "claude-sonnet-4-6"
    mock_settings.litellm_alt_provider_id = "mentor-api"
    mock_settings.litellm_alt_display_name = "Mentor (API)"

    provider = resolve_provider("mentor-api")
    assert provider is not None
    assert provider.id == "mentor-api"


@patch("app.config.settings")
def test_resolve_provider_case_insensitive(mock_settings):
    """Case-insensitive matching → 'MENTOR-API' matches 'mentor-api'."""
    mock_settings.litellm_model = "sonnet"
    mock_settings.litellm_base_url = "http://proxy:3456/v1"
    mock_settings.litellm_key = "sk-dev"
    mock_settings.litellm_provider_id = "mentor-sub"
    mock_settings.litellm_display_name = "Mentor (Sub)"
    mock_settings.litellm_alt_base_url = "https://api.anthropic.com"
    mock_settings.litellm_alt_key = "sk-ant"
    mock_settings.litellm_alt_model = "claude-sonnet-4-6"
    mock_settings.litellm_alt_provider_id = "mentor-api"
    mock_settings.litellm_alt_display_name = "Mentor (API)"

    provider = resolve_provider("MENTOR-API")
    assert provider is not None
    assert provider.id == "mentor-api"


@patch("app.config.settings")
def test_resolve_provider_unknown_returns_none(mock_settings):
    """Explicit but unknown model ID → returns None."""
    mock_settings.litellm_model = "sonnet"
    mock_settings.litellm_base_url = "http://proxy:3456/v1"
    mock_settings.litellm_key = "sk-dev"
    mock_settings.litellm_provider_id = "mentor-sub"
    mock_settings.litellm_display_name = "Mentor (Sub)"
    mock_settings.litellm_alt_base_url = ""

    provider = resolve_provider("nonexistent-model")
    assert provider is None


# ---------------------------------------------------------------------------
# ProviderConfig is frozen
# ---------------------------------------------------------------------------

def test_provider_config_is_frozen():
    """ProviderConfig should be immutable (frozen dataclass)."""
    p = ProviderConfig(id="test", display_name="Test", base_url="http://x", api_key="k", model="m")
    try:
        p.id = "new-id"  # type: ignore[misc]
        assert False, "Should have raised FrozenInstanceError"
    except AttributeError:
        pass
