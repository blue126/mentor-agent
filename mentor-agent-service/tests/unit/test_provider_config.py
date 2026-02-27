"""Unit tests for ProviderConfig, get_providers(), resolve_provider(), and YAML loading."""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import (
    ConfigurationError,
    ProviderConfig,
    _expand_env_vars,
    _normalize_model_for_litellm,
    _sanitize_provider_id,
    get_providers,
    load_providers_from_yaml,
    reset_providers_cache,
    resolve_provider,
)

# ---------------------------------------------------------------------------
# _normalize_model_for_litellm tests
# ---------------------------------------------------------------------------


def test_normalize_proxy_url_adds_openai_prefix():
    """Proxy URL → model gets 'openai/' prefix."""
    result = _normalize_model_for_litellm("sonnet", "http://unified-proxy:3456/v1")
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
    assert _sanitize_provider_id("claude-sub") == "claude-sub"


def test_sanitize_provider_id_logs_warning():
    """Sanitization should log a warning when ID is modified."""
    with patch("app.config.logger") as mock_logger:
        _sanitize_provider_id("openai/model")
    mock_logger.warning.assert_called_once()
    assert "sanitized" in mock_logger.warning.call_args[0][0].lower()


# ---------------------------------------------------------------------------
# _expand_env_vars tests
# ---------------------------------------------------------------------------


def test_expand_env_vars_resolves(monkeypatch: pytest.MonkeyPatch):
    """${ENV_VAR} is replaced with its value."""
    monkeypatch.setenv("MY_KEY", "secret-123")
    assert _expand_env_vars("${MY_KEY}") == "secret-123"


def test_expand_env_vars_missing_returns_none(monkeypatch: pytest.MonkeyPatch):
    """Missing env var → returns None."""
    monkeypatch.delenv("NONEXISTENT_VAR_XYZ", raising=False)
    assert _expand_env_vars("${NONEXISTENT_VAR_XYZ}") is None


def test_expand_env_vars_literal_passthrough():
    """No ${...} pattern → string returned as-is."""
    assert _expand_env_vars("plain-key") == "plain-key"


# ---------------------------------------------------------------------------
# load_providers_from_yaml tests
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test-providers.yaml"
    p.write_text(content)
    return p


def test_load_providers_basic(tmp_path: Path):
    """Basic YAML with one provider loads correctly."""
    yaml_file = _write_yaml(tmp_path, """\
providers:
  - id: "claude-sub"
    display_name: "Claude (Subscription)"
    base_url: "http://unified-proxy:3456/v1"
    api_key: "sk-dev"
    model: "claude-sonnet-4-6"
""")
    providers = load_providers_from_yaml(yaml_file)
    assert len(providers) == 1
    p = providers[0]
    assert p.id == "claude-sub"
    assert p.display_name == "Claude (Subscription)"
    assert p.base_url == "http://unified-proxy:3456/v1"
    assert p.api_key == "sk-dev"
    assert p.model == "openai/claude-sonnet-4-6"  # proxy → openai/ prefix


def test_load_providers_multiple(tmp_path: Path):
    """Multiple providers in YAML → all loaded."""
    yaml_file = _write_yaml(tmp_path, """\
providers:
  - id: "claude-sub"
    display_name: "Claude (Subscription)"
    base_url: "http://proxy:3456/v1"
    api_key: "sk-dev"
    model: "sonnet"
  - id: "mentor-api"
    display_name: "Mentor (API)"
    base_url: "https://api.anthropic.com"
    api_key: "sk-ant-xxx"
    model: "claude-sonnet-4-6"
""")
    providers = load_providers_from_yaml(yaml_file)
    assert len(providers) == 2
    assert providers[0].id == "claude-sub"
    assert providers[0].model == "openai/sonnet"
    assert providers[1].id == "mentor-api"
    assert providers[1].model == "claude-sonnet-4-6"  # direct API → no prefix


def test_load_providers_missing_file(tmp_path: Path):
    """Non-existent YAML file → ConfigurationError."""
    with pytest.raises(ConfigurationError, match="not found"):
        load_providers_from_yaml(tmp_path / "nope.yaml")


def test_load_providers_invalid_yaml(tmp_path: Path):
    """Malformed YAML → ConfigurationError."""
    yaml_file = _write_yaml(tmp_path, "{{not valid yaml}}")
    with pytest.raises(ConfigurationError, match="Invalid YAML"):
        load_providers_from_yaml(yaml_file)


def test_load_providers_missing_providers_key(tmp_path: Path):
    """YAML without 'providers' key → ConfigurationError."""
    yaml_file = _write_yaml(tmp_path, "something_else: true\n")
    with pytest.raises(ConfigurationError, match="expected top-level"):
        load_providers_from_yaml(yaml_file)


def test_load_providers_skips_invalid_entries(tmp_path: Path):
    """Provider with missing required field → skipped with warning, valid ones kept."""
    yaml_file = _write_yaml(tmp_path, """\
providers:
  - id: "good"
    display_name: "Good"
    base_url: "http://proxy:3456/v1"
    api_key: "sk-dev"
    model: "sonnet"
  - id: "bad-no-model"
    display_name: "Bad"
    base_url: "http://proxy:3456/v1"
    api_key: "sk-dev"
""")
    providers = load_providers_from_yaml(yaml_file)
    assert len(providers) == 1
    assert providers[0].id == "good"


def test_load_providers_all_invalid_raises(tmp_path: Path):
    """All providers invalid → ConfigurationError (zero valid providers)."""
    yaml_file = _write_yaml(tmp_path, """\
providers:
  - id: "bad"
    display_name: "Bad"
    base_url: "not-a-url"
    api_key: "sk-dev"
    model: "sonnet"
""")
    with pytest.raises(ConfigurationError, match="No valid provider"):
        load_providers_from_yaml(yaml_file)


def test_load_providers_env_var_expansion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """${ENV_VAR} in api_key gets expanded."""
    monkeypatch.setenv("TEST_API_KEY", "resolved-secret")
    yaml_file = _write_yaml(tmp_path, """\
providers:
  - id: "test"
    display_name: "Test"
    base_url: "http://proxy:3456/v1"
    api_key: "${TEST_API_KEY}"
    model: "sonnet"
""")
    providers = load_providers_from_yaml(yaml_file)
    assert providers[0].api_key == "resolved-secret"


def test_load_providers_unresolved_env_var_skips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Unresolved ${ENV_VAR} → provider skipped."""
    monkeypatch.delenv("NONEXISTENT_KEY_XYZ", raising=False)
    yaml_file = _write_yaml(tmp_path, """\
providers:
  - id: "good"
    display_name: "Good"
    base_url: "http://proxy:3456/v1"
    api_key: "literal-key"
    model: "sonnet"
  - id: "bad"
    display_name: "Bad"
    base_url: "http://proxy:3456/v1"
    api_key: "${NONEXISTENT_KEY_XYZ}"
    model: "sonnet"
""")
    providers = load_providers_from_yaml(yaml_file)
    assert len(providers) == 1
    assert providers[0].id == "good"


def test_load_providers_id_sanitization(tmp_path: Path):
    """Provider ID with '/' → sanitized to '-'."""
    yaml_file = _write_yaml(tmp_path, """\
providers:
  - id: "openai/sonnet"
    display_name: "Test"
    base_url: "http://proxy:3456/v1"
    api_key: "sk-dev"
    model: "sonnet"
""")
    providers = load_providers_from_yaml(yaml_file)
    assert providers[0].id == "openai-sonnet"


def test_load_providers_model_normalization(tmp_path: Path):
    """Proxy URL → model gets openai/ prefix; direct API → no prefix."""
    yaml_file = _write_yaml(tmp_path, """\
providers:
  - id: "proxy-provider"
    display_name: "Proxy"
    base_url: "http://proxy:3456/v1"
    api_key: "sk-dev"
    model: "sonnet"
  - id: "direct-provider"
    display_name: "Direct"
    base_url: "https://api.anthropic.com"
    api_key: "sk-ant"
    model: "claude-sonnet-4-6"
""")
    providers = load_providers_from_yaml(yaml_file)
    assert providers[0].model == "openai/sonnet"
    assert providers[1].model == "claude-sonnet-4-6"


def test_load_providers_invalid_base_url_skips(tmp_path: Path):
    """Invalid base_url (not http/https) → provider skipped."""
    yaml_file = _write_yaml(tmp_path, """\
providers:
  - id: "good"
    display_name: "Good"
    base_url: "http://proxy:3456/v1"
    api_key: "sk-dev"
    model: "sonnet"
  - id: "bad"
    display_name: "Bad"
    base_url: "ftp://invalid.com/v1"
    api_key: "sk-dev"
    model: "sonnet"
""")
    providers = load_providers_from_yaml(yaml_file)
    assert len(providers) == 1
    assert providers[0].id == "good"


# ---------------------------------------------------------------------------
# get_providers() tests — YAML-only loading
# ---------------------------------------------------------------------------


def test_get_providers_from_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """get_providers() loads from PROVIDERS_YAML_PATH."""
    yaml_file = _write_yaml(tmp_path, """\
providers:
  - id: "claude-sub"
    display_name: "Mentor (Sub)"
    base_url: "http://proxy:3456/v1"
    api_key: "sk-dev"
    model: "sonnet"
""")
    reset_providers_cache()
    from app.config import settings as _settings
    monkeypatch.setattr(_settings, "providers_yaml_path", str(yaml_file))

    providers = get_providers()
    assert len(providers) == 1
    assert providers[0].id == "claude-sub"


def test_get_providers_missing_yaml_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """No YAML file anywhere → ConfigurationError."""
    reset_providers_cache()
    from app.config import settings as _settings
    monkeypatch.setattr(_settings, "providers_yaml_path", str(tmp_path / "nope.yaml"))

    with pytest.raises(ConfigurationError, match="not found"):
        get_providers()


def test_get_providers_caches_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """get_providers() caches after first call."""
    yaml_file = _write_yaml(tmp_path, """\
providers:
  - id: "cached"
    display_name: "Cached"
    base_url: "http://proxy:3456/v1"
    api_key: "sk-dev"
    model: "sonnet"
""")
    reset_providers_cache()
    from app.config import settings as _settings
    monkeypatch.setattr(_settings, "providers_yaml_path", str(yaml_file))

    p1 = get_providers()
    p2 = get_providers()
    assert p1 is p2  # Same object — cached


def test_get_providers_default_location(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Empty PROVIDERS_YAML_PATH → falls back to ./providers.yaml if it exists."""
    reset_providers_cache()
    from app.config import settings as _settings
    monkeypatch.setattr(_settings, "providers_yaml_path", "")
    # Change CWD to tmp_path so ./providers.yaml is found there
    monkeypatch.chdir(tmp_path)
    yaml_file = tmp_path / "providers.yaml"
    yaml_file.write_text("""\
providers:
  - id: "default-location"
    display_name: "Default"
    base_url: "http://proxy:3456/v1"
    api_key: "sk-dev"
    model: "sonnet"
""")

    providers = get_providers()
    assert len(providers) == 1
    assert providers[0].id == "default-location"


def test_get_providers_no_yaml_anywhere_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """No PROVIDERS_YAML_PATH and no ./providers.yaml → ConfigurationError."""
    reset_providers_cache()
    from app.config import settings as _settings
    monkeypatch.setattr(_settings, "providers_yaml_path", "")
    # Use a subdirectory that has no providers.yaml (autouse fixture writes to tmp_path)
    empty_dir = tmp_path / "empty_subdir"
    empty_dir.mkdir()
    monkeypatch.chdir(empty_dir)

    with pytest.raises(ConfigurationError, match="not found"):
        get_providers()


# ---------------------------------------------------------------------------
# resolve_provider() tests
# ---------------------------------------------------------------------------


def test_resolve_provider_none_returns_primary():
    """None model_id → returns primary provider (backwards compat)."""
    provider = resolve_provider(None)
    assert provider is not None
    assert provider.id == "test-provider"  # from autouse fixture


def test_resolve_provider_empty_string_returns_primary():
    """Empty string model_id → returns primary provider."""
    provider = resolve_provider("")
    assert provider is not None
    assert provider.id == "test-provider"


def test_resolve_provider_matches_by_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Exact ID match → returns that provider."""
    yaml_file = _write_yaml(tmp_path, """\
providers:
  - id: "claude-sub"
    display_name: "Mentor (Sub)"
    base_url: "http://proxy:3456/v1"
    api_key: "sk-dev"
    model: "sonnet"
  - id: "mentor-api"
    display_name: "Mentor (API)"
    base_url: "https://api.anthropic.com"
    api_key: "sk-ant"
    model: "claude-sonnet-4-6"
""")
    reset_providers_cache()
    from app.config import settings as _settings
    monkeypatch.setattr(_settings, "providers_yaml_path", str(yaml_file))

    provider = resolve_provider("mentor-api")
    assert provider is not None
    assert provider.id == "mentor-api"


def test_resolve_provider_case_insensitive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Case-insensitive matching → 'MENTOR-API' matches 'mentor-api'."""
    yaml_file = _write_yaml(tmp_path, """\
providers:
  - id: "claude-sub"
    display_name: "Mentor (Sub)"
    base_url: "http://proxy:3456/v1"
    api_key: "sk-dev"
    model: "sonnet"
  - id: "mentor-api"
    display_name: "Mentor (API)"
    base_url: "https://api.anthropic.com"
    api_key: "sk-ant"
    model: "claude-sonnet-4-6"
""")
    reset_providers_cache()
    from app.config import settings as _settings
    monkeypatch.setattr(_settings, "providers_yaml_path", str(yaml_file))

    provider = resolve_provider("MENTOR-API")
    assert provider is not None
    assert provider.id == "mentor-api"


def test_resolve_provider_unknown_returns_none():
    """Explicit but unknown model ID → returns None."""
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
