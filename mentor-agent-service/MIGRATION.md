# Provider Configuration Migration Guide

## What Changed (Story 1.7)

Provider configuration has been migrated from environment variables (`LITELLM_*`) to a YAML-based configuration file (`providers.yaml`).

**Breaking change:** The service will **not start** without a valid `providers.yaml` file. All `LITELLM_*` environment variables are no longer read.

## Migration Steps

### 1. Create `providers.yaml`

Create a `providers.yaml` file in the project root (or specify its path via `PROVIDERS_YAML_PATH` env var):

```yaml
providers:
  - id: "claude-sub"
    display_name: "Claude Sonnet 4.6"
    base_url: "http://unified-proxy:3456/v1"
    api_key: "sk-unused"              # OAuth handled by proxy
    model: "claude-sonnet-4-6"

  - id: "nvidia-nim"
    display_name: "NVIDIA NIM (Llama 3.1 70B)"
    base_url: "https://integrate.api.nvidia.com/v1"
    api_key: "${NVIDIA_NIM_API_KEY}"
    model: "openai/meta/llama-3.1-70b-instruct"

  - id: "gpt-sub"
    display_name: "GPT-5.2"
    base_url: "http://unified-proxy:3456/v1"
    api_key: "sk-unused"              # OAuth handled by proxy
    model: "gpt-5.2"
```

### 2. Map your old env vars

| Old Env Var | New YAML Field | Notes |
|---|---|---|
| `LITELLM_BASE_URL` | `base_url` | |
| `LITELLM_KEY` | `api_key` | Supports `${ENV_VAR}` syntax |
| `LITELLM_MODEL` | `model` | |
| `LITELLM_PROVIDER_ID` | `id` | Required in YAML |
| `LITELLM_DISPLAY_NAME` | `display_name` | Required in YAML |
| `LITELLM_ALT_*` | Second entry in `providers` list | |

### 3. Remove old env vars from `.env`

Remove these from your `.env` file (they are no longer read):
- `LITELLM_BASE_URL`
- `LITELLM_KEY`
- `LITELLM_MODEL`
- `LITELLM_PROVIDER_ID`
- `LITELLM_DISPLAY_NAME`
- `LITELLM_ALT_BASE_URL`
- `LITELLM_ALT_KEY`
- `LITELLM_ALT_MODEL`
- `LITELLM_ALT_PROVIDER_ID`
- `LITELLM_ALT_DISPLAY_NAME`

### 4. Add API key env vars (if using `${ENV_VAR}` in YAML)

Add the API key env vars that your `providers.yaml` references:
```
NVIDIA_NIM_API_KEY=your-nvidia-nim-key
```
Note: Subscription providers (claude-sub, gpt-sub) use `api_key: "sk-unused"` — OAuth is handled by unified-proxy.

### 5. Verify

```bash
# Start the service
python -m uvicorn app.main:app --port 8100

# Check provider loading
# Look for: "Successfully loaded N providers: [...]"

# Verify models endpoint
curl http://localhost:8100/v1/models
```

## Troubleshooting

**"Provider configuration file not found"**
- Create `providers.yaml` in the project root, or set `PROVIDERS_YAML_PATH` to the file path.

**"Invalid YAML format"**
- Check YAML syntax. Use a YAML validator if needed.

**"No valid provider found"**
- Check that all required fields are present: `id`, `display_name`, `base_url`, `api_key`, `model`
- Check that `base_url` starts with `http://` or `https://`
- Check that env vars referenced in `api_key` (e.g., `${MY_KEY}`) are set

**"Skipped provider 'X' (unresolved env var)"**
- The referenced env var is not set. Add it to `.env` or export it.

## Docker Compose

The `docker-compose.yml` now mounts `providers.yaml` into the container:
```yaml
volumes:
  - ./providers.yaml:/app/providers.yaml:ro
environment:
  - PROVIDERS_YAML_PATH=/app/providers.yaml
```

## Unified Proxy Migration (Story 1.7 Phase 2)

### What Changed

`claude-max-proxy` has been upgraded to **unified-proxy** — a single proxy that handles both Anthropic Claude and OpenAI GPT-5.2 via OAuth subscriptions. The separate `codex-proxy` container has been eliminated. The ChatGPT Backend conversion logic (Chat Completions → Codex Responses format) has been ported from codex-proxy (Go) to unified-proxy (Node.js).

| Before | After |
|---|---|
| `claude-max-proxy` (Anthropic only) + `codex-proxy` (OpenAI only) | `unified-proxy` (both Anthropic + OpenAI) |
| 5 containers | 4 containers |
| `~/.claude-max-proxy/auth.json` (flat) | `~/.unified-proxy/auth.json` (dual-section) |
| `PROXY_AUTH_DIR=~/.claude-max-proxy` | `PROXY_AUTH_DIR=~/.unified-proxy` |

### Credential Migration

1. **Auto-migration:** If `~/.unified-proxy/auth.json` does not exist but `~/.claude-max-proxy/auth.json` does, the proxy auto-migrates on startup (copies and converts flat format to dual-section).

2. **Manual migration:** Copy your existing auth file:
   ```bash
   mkdir -p ~/.unified-proxy
   cp ~/.claude-max-proxy/auth.json ~/.unified-proxy/auth.json
   ```
   The proxy will auto-convert the flat format to dual-section on first startup.

3. **Fresh setup:** Run OAuth login for both providers:
   ```bash
   cd unified-proxy && node server.js --login all
   ```

### Auth File Format

**Old (flat):**
```json
{ "accessToken": "...", "refreshToken": "...", "expiresAt": ... }
```

**New (dual-section):**
```json
{
  "anthropic": { "accessToken": "...", "refreshToken": "...", "expiresAt": ... },
  "openai": { "accessToken": "...", "refreshToken": "...", "expiresAt": ..., "accountId": "..." }
}
```

### providers.yaml Changes

Update `base_url` references from `claude-max-proxy` to `unified-proxy`:
```yaml
providers:
  - id: "claude-sub"
    base_url: "http://unified-proxy:3456/v1"  # was: claude-max-proxy:3456
    # ...

  - id: "gpt-sub"
    base_url: "http://unified-proxy:3456/v1"  # same endpoint, proxy routes by model
    api_key: "sk-unused"                       # OAuth handled by proxy
    model: "gpt-5.2"
```

### .env Changes

```bash
# Old:
PROXY_AUTH_DIR=~/.claude-max-proxy
# CODEX_PROXY_AUTH_DIR=~/.config/codex-proxy

# New:
PROXY_AUTH_DIR=~/.unified-proxy
# CODEX_PROXY_AUTH_DIR removed (no longer needed)
```
