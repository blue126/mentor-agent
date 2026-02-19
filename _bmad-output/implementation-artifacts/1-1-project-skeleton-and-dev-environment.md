# Story 1.1: 项目骨架与开发环境初始化

Status: ready-for-dev

## Story

As a developer,
I want a fully initialized FastAPI project skeleton with Docker Compose, Alembic, and dev tooling,
so that I have a solid foundation to build the Agent Service upon.

## Acceptance Criteria

1. **Given** 开发者克隆了代码仓库 **When** 运行 `docker compose up` **Then** agent-service 容器启动成功，监听端口 8100
2. **And** `GET /health` 返回 `{"status": "ok"}`
3. **And** 项目目录结构符合架构文档定义（app/routers, app/services, app/repositories, app/tools, app/utils, tests/）
4. **And** Alembic 初始化完成，可运行 `alembic upgrade head`
5. **And** 首次 migration 创建基础 `users` 表（id, name, current_context, skill_level）
6. **And** `.env.example` 包含所有必要的环境变量模板
7. **And** `pyproject.toml` 包含所有生产和开发依赖
8. **And** 全局采用 snake_case 命名规范

## Tasks / Subtasks

- [ ] Task 1: Create project root directory structure (AC: #3)
  - [ ] 1.1 Create `mentor-agent-service/` root with `app/`, `tests/`, `alembic/`, `data/` directories
  - [ ] 1.2 Create all sub-packages: `app/routers/`, `app/services/`, `app/repositories/`, `app/tools/`, `app/utils/`
  - [ ] 1.3 Add `__init__.py` to every Python package directory
- [ ] Task 2: Create pyproject.toml with all dependencies (AC: #7)
  - [ ] 2.1 Production deps: fastapi[standard]>=0.129.0, uvicorn, httpx, litellm>=1.81.0, aiosqlite, pydantic-settings, alembic>=1.18.0, networkx
  - [ ] 2.2 Dev deps: pytest, pytest-asyncio, httpx (TestClient), vcrpy, ruff, mypy
  - [ ] 2.3 Add project metadata, Python >=3.11 requirement, and tool configs (ruff, mypy, pytest)
- [ ] Task 3: Create Dockerfile and docker-compose.yml (AC: #1)
  - [ ] 3.1 Dockerfile: Python 3.12-slim base, install deps, copy app, expose 8100, CMD uvicorn
  - [ ] 3.2 docker-compose.yml: agent-service on port 8100, volume mount for data/mentor.db, network for future services
  - [ ] 3.3 Add placeholder service entries (commented) for open-webui, litellm-claude-code, anki
- [ ] Task 4: Create FastAPI application entry point (AC: #1, #2)
  - [ ] 4.1 `app/main.py`: FastAPI app factory with lifespan, include routers
  - [ ] 4.2 `app/config.py`: pydantic-settings class loading from .env (DB path, API keys, LiteLLM URL, port)
  - [ ] 4.3 `app/dependencies.py`: DI providers for DB session, config
  - [ ] 4.4 `app/routers/health.py`: `GET /health` returning `{"status": "ok"}`
- [ ] Task 5: Initialize Alembic with async SQLite support (AC: #4, #5)
  - [ ] 5.1 `alembic init alembic` → configure `alembic.ini` with SQLite URL from config
  - [ ] 5.2 `alembic/env.py`: configure for async SQLite using `run_async` pattern
  - [ ] 5.3 Create first migration: `users` table (id INTEGER PK, name TEXT, current_context TEXT, skill_level TEXT)
  - [ ] 5.4 Verify `alembic upgrade head` creates table successfully
- [ ] Task 6: Create .env.example and .gitignore (AC: #6)
  - [ ] 6.1 `.env.example` with: DATABASE_URL, LITELLM_BASE_URL, LITELLM_KEY, OPENWEBUI_API_KEY, NOTION_TOKEN, NOTION_DB_ID, AGENT_API_KEY
  - [ ] 6.2 `.gitignore`: data/*.db, .env, __pycache__, .venv, .mypy_cache, .ruff_cache
- [ ] Task 7: Create stub files for future modules (AC: #3)
  - [ ] 7.1 `app/routers/chat.py`: empty placeholder with TODO comment
  - [ ] 7.2 `app/services/agent_service.py`: empty placeholder
  - [ ] 7.3 `app/services/graph_service.py`: empty placeholder
  - [ ] 7.4 `app/services/quiz_service.py`: empty placeholder
  - [ ] 7.5 `app/repositories/user_repo.py`: empty placeholder
  - [ ] 7.6 `app/repositories/progress_repo.py`: empty placeholder
  - [ ] 7.7 `app/tools/registry.py`: empty tool registry dict
  - [ ] 7.8 `app/tools/definitions.py`: empty placeholder
  - [ ] 7.9 `app/utils/sse_generator.py`: empty placeholder
- [ ] Task 8: Create test infrastructure (AC: #3)
  - [ ] 8.1 `tests/conftest.py`: pytest-asyncio fixtures, async httpx TestClient, in-memory SQLite
  - [ ] 8.2 `tests/unit/` and `tests/integration/` directories with `__init__.py`
  - [ ] 8.3 `tests/cassettes/` directory for vcrpy recordings
  - [ ] 8.4 Basic smoke test: `test_health.py` → assert GET /health returns 200 + correct JSON
- [ ] Task 9: Verify full cycle (AC: #1, #2, #4)
  - [ ] 9.1 `docker compose build && docker compose up -d`
  - [ ] 9.2 `curl http://localhost:8100/health` returns `{"status":"ok"}`
  - [ ] 9.3 Run `alembic upgrade head` inside container, verify `users` table exists
  - [ ] 9.4 Run `pytest` inside container, all tests pass

## Dev Notes

### Architecture Compliance (MANDATORY)

- **Project root name:** `mentor-agent-service/` [Source: architecture.md#Section 5]
- **Naming convention:** snake_case everywhere — DB tables, columns, API JSON keys, Python variables/functions/files [Source: architecture.md#Section 4]
- **Layer boundaries:** routers → services → repositories. Tools call services, never DB directly [Source: architecture.md#Section 5]
- **Error pattern:** Fail Soft with Hints — no raised exceptions crashing the app, return error strings [Source: architecture.md#Section 4]
- **Async mandate:** All I/O must be async. Use `httpx` (not `requests`), `aiosqlite` (not `sqlite3`), `asyncio.sleep` (not `time.sleep`) [Source: architecture.md#Section 4]

### Technical Stack (Pin These Versions)

| Package | Version | Notes |
|---------|---------|-------|
| fastapi[standard] | >=0.129.0 | Latest as of 2026-02-19, requires Python >=3.10 |
| uvicorn | latest | Included via fastapi[standard] |
| httpx | latest | Async HTTP client for LiteLLM & Open WebUI calls |
| litellm | >=1.81.0 | LLM proxy library, supports Anthropic tool_use |
| aiosqlite | latest | Async SQLite driver |
| pydantic-settings | latest | .env-based config management |
| alembic | >=1.18.0 | DB migration tool, supports SQLite batch mode |
| networkx | latest | In-memory graph algorithms (future epics) |
| pytest | latest | Test runner |
| pytest-asyncio | latest | Async test support |
| vcrpy | latest | LLM interaction recording/replay |
| ruff | latest | Linter + formatter |

### Docker Compose Structure

The `docker-compose.yml` must define these services (only agent-service active in Story 1.1; others commented):

```yaml
services:
  agent-service:
    build: .
    ports:
      - "8100:8100"
    volumes:
      - ./data:/app/data
    env_file: .env
    restart: unless-stopped
  # open-webui: (Story 1.2)
  # litellm-claude-code: (Story 1.2)
  # anki: (Epic 5)
```

### Alembic + Async SQLite

Alembic with async SQLite requires special `env.py` configuration. Use the `run_async` migration runner pattern:

```python
# alembic/env.py key pattern
from sqlalchemy.ext.asyncio import create_async_engine

async def run_async_migrations():
    connectable = create_async_engine(config.get_main_option("sqlalchemy.url"))
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
```

SQLite ALTER limitations: use Alembic batch mode (`with op.batch_alter_table(...)`) for any table modifications in future migrations.

### .env.example Template

```
# Agent Service
AGENT_API_KEY=your-bearer-token-here
DATABASE_URL=sqlite+aiosqlite:///./data/mentor.db

# LiteLLM (Cloud LLM Access)
LITELLM_BASE_URL=http://litellm-claude-code:4000/v1
LITELLM_KEY=your-litellm-key

# Open WebUI (RAG Retrieval)
OPENWEBUI_BASE_URL=http://open-webui:8080
OPENWEBUI_API_KEY=your-openwebui-api-key

# Notion Integration (Optional)
NOTION_TOKEN=
NOTION_DB_ID=

# AnkiConnect (Optional)
ANKI_CONNECT_URL=http://anki:8765
```

### Project Structure Notes

- Directory structure MUST match architecture.md Section 5 exactly — no deviations
- `data/` directory is the SQLite mount point, gitignored
- `tests/cassettes/` stores vcrpy recordings for stable LLM testing
- All `__init__.py` files can be empty but MUST exist for proper package resolution

### Anti-Patterns to AVOID

- DO NOT use `requirements.txt` as primary — use `pyproject.toml` with optional `requirements.txt` generated from it
- DO NOT use synchronous `sqlite3` or `requests` anywhere
- DO NOT put business logic in routers — routers only handle HTTP protocol translation
- DO NOT put DB access in tools — tools call services which call repositories
- DO NOT hardcode any secrets — everything through pydantic-settings and .env

### References

- [Source: architecture.md#Section 2] — Starter template decision and initialization command
- [Source: architecture.md#Section 4] — Implementation patterns: snake_case, Fail Soft, async mandate
- [Source: architecture.md#Section 5] — Complete project directory structure
- [Source: architecture.md#Section 3] — Data architecture: SQLite + Alembic + NetworkX hybrid
- [Source: epics.md#Story 1.1] — Original acceptance criteria
- [Source: prd.md#Section 8] — MVP scope: Docker Compose 4 services

## Dev Agent Record

### Agent Model Used

(To be filled by dev agent)

### Debug Log References

### Completion Notes List

### File List
