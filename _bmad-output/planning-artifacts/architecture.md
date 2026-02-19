---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
inputDocuments: ["_bmad-output/planning-artifacts/prd.md", "plan.md"]
workflowType: 'architecture'
project_name: 'mentor-agent'
user_name: 'Will'
date: '2026-02-19'
lastStep: 8
status: 'complete'
completedAt: '2026-02-19'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## 1. Project Context Analysis

### Architecture Overview

Mentor Agent 采用 **Agent-as-LLM-Proxy** 模式：Agent Service 对外暴露 OpenAI 兼容 API，让 Open WebUI 将其视为一个 "模型"，而 Agent Service 内部维护完整的 Tool Use 循环，通过 LiteLLM 调用云端 LLM（Claude / OpenAI）完成推理。

**核心数据流：**

```
User → Open WebUI → Agent Service (FastAPI, OpenAI 兼容 API)
                         ↓
                    LiteLLM (litellm-claude-code) → Claude / OpenAI (云端订阅)
                         ↓
                    Claude 返回 tool_use 指令
                         ↓
                    Agent Service 执行工具 (SQLite, Open WebUI RAG, Notion, Anki...)
                         ↓
                    工具结果回传 Claude → 循环直到生成最终回复
                         ↓
                    Agent Service 以 OpenAI SSE Streaming 格式返回给 Open WebUI
```

**关键设计决策：**
- Open WebUI **完全感知不到** 后面的 Tool Use 循环，只收到最终文本回复
- Agent Service 是唯一的编排中心，所有工具调用由它协调
- LLM 推理依赖用户的 Anthropic / OpenAI **云端订阅**，通过 `litellm-claude-code` 代理访问

### Requirements Overview

**Functional Requirements:**
- **核心学习闭环：** "Teach Me" 苏格拉底式教学、Quiz 生成与评分、进度追踪、前置知识检查
- **数据摄入：** 用户上传 PDF 到 Open WebUI，Agent 通过 RAG 检索生成学习计划
- **知识图谱：** 自动提取概念间关系（前置、相关、应用），支持跨书本关联
- **教学模式：** 类比解释、前置检查、错误模式分析、实践场景生成
- **外部集成：** Notion（会话总结）、Anki（闪卡生成，homelab Linux + AnkiConnect）

**Non-Functional Requirements:**
- **Local-First & Privacy：** 用户数据（进度、图谱、Quiz 历史）存储在本地 SQLite；LLM 推理通过云端 API
- **Performance：** 普通对话 < 3s，RAG 检索 < 10s，学习计划生成 < 30s
- **Resilience：** Notion / Anki 调用失败不阻塞主流程，优雅降级
- **Deployment：** Docker Compose 一键部署（Open WebUI + Agent Service + LiteLLM + Anki）

### Technical Constraints & Dependencies

| 约束 | 说明 |
|------|------|
| **Open WebUI（硬约束）** | 作为唯一前端界面，Agent Service 通过其 OpenAI API 配置接入 |
| **LiteLLM-Claude-Code（硬约束）** | 基于 Claude Max 订阅的 OAuth 代理，Agent Service 通过它访问云端 LLM |
| **FastAPI（已选定）** | Agent Service 后端框架，需实现 OpenAI 兼容 API + SSE Streaming |
| **SQLite（已选定）** | 本地结构化数据存储，单用户无并发压力 |
| **Open WebUI RAG API（依赖）** | `search_knowledge_base` 工具需反向调用 Open WebUI 的检索接口 |
| **Docker Compose 网络** | 所有服务在同一网络中通过服务名互访 |

### Known Trade-offs (已知取舍)

1. **Open WebUI 知识库选择界面不可用：** RAG 检索由 Agent Service 内部工具负责，Open WebUI 的手动知识库选择功能失效。替代方案：Agent 自动判断或用户在对话中指定
2. **Open WebUI 模型切换不可用：** Open WebUI 中的 "模型" 实际是 Agent Service，无法切换底层 LLM。需在 Agent Service 配置中指定
3. **Tool Use 延迟：** 多轮工具调用循环可能导致较长等待，需要通过 SSE streaming 提供中间状态反馈

### Risk Assessment (风险评估)

| 风险 | 级别 | 缓解策略 |
|------|------|----------|
| Open WebUI RAG API 稳定性 / 文档不足 | ⚠️ 中 | 调研 API 能力；准备备用轻量级检索方案 |
| LiteLLM tool_use 格式转译兼容性 | ⚠️ 中 | 早期验证 litellm-claude-code 的 tool_use 支持；必要时直接调用 Anthropic API |
| SSE Streaming 实现复杂度 | ⚠️ 中 | Tool Use 循环期间需要合理的中间状态推送策略 |
| Anki Linux 容器化 | ⚠️ 低-中 | AnkiConnect 需要 GUI 环境，Docker 中可能需要 headless 配置 |
| Claude Max 订阅 Token 过期 / 限流 | ⚠️ 低 | 监控 Token 状态，提供清晰的错误提示 |

### Scale & Complexity

- **项目复杂度：** **High**（Agent 编排 + Tool Use 循环 + RAG + 知识图谱 + 多外部集成）
- **主要技术领域：** Backend / AI Agent Engineering（Python / FastAPI）
- **核心组件数量：** ~5 个容器服务 + 12 个工具函数
- **前端工作量：** 极低（完全依赖 Open WebUI 原生界面）

## 2. Starter Template Evaluation

### Primary Technology Domain

**Backend / AI Agent Engineering (Python/FastAPI)** — 本项目不是传统 Web 应用，而是一个 Agent Service，传统前端 Starter Template 不适用。

### Starter Options Considered

| Option | Description | Verdict |
|--------|-------------|---------|
| FastAPI Official Template (`fastapi[standard]`) | Basic routing + Uvicorn | Too minimal for Agent orchestration |
| LangChain/LangGraph Template | Agent orchestration framework | Over-abstraction; project needs direct Tool Use loop control |
| **Custom FastAPI Project Structure** | Hand-crafted modular architecture | **Selected** — Maximum flexibility for non-standard Agent-as-LLM-Proxy pattern |

### Selected Starter: Custom FastAPI Project Structure

**Rationale:**
1. Agent-as-LLM-Proxy is a non-standard pattern with no existing template match
2. OpenAI-compatible API + SSE Streaming requires custom implementation
3. 12 tool functions need clean modular organization
4. Avoids unnecessary framework overhead (LangChain, etc.)
5. **Team Input:** Added `alembic` for future-proof DB migrations and `vcrpy` for stable testing of LLM interactions.

**Initialization Command:**

```bash
mkdir mentor-agent-service && cd mentor-agent-service
python -m venv .venv
pip install "fastapi[standard]" uvicorn httpx litellm aiosqlite pydantic-settings alembic vcrpy
alembic init alembic
```

**Architectural Decisions Provided by Starter:**

| Decision | Choice |
|----------|--------|
| **Language & Runtime** | Python 3.11+, strict type hints |
| **API Framework** | FastAPI + Uvicorn (ASGI) |
| **Async Model** | Full async/await for SSE Streaming compatibility |
| **Configuration** | pydantic-settings (env vars + .env) |
| **HTTP Client** | httpx (async calls to LiteLLM & Open WebUI API) |
| **Database** | aiosqlite (async SQLite access) + **Alembic (Migrations)** |
| **Testing** | pytest + httpx (FastAPI TestClient) + **vcrpy (LLM Mocking)** |
| **Code Organization** | Modular layering: routers / services / repositories / tools |

**Note:** Project initialization using this setup should be the first implementation story.

## 3. Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**
- **Data Model Strategy:** Option C (Graph Layer via NetworkX + SQLite Persistence)
- **Agent Service Auth:** Option A (Static Bearer Token)
- **Tool Execution Mode:** Option B (Async SSE Streaming with status updates)

**Important Decisions (Shape Architecture):**
- **External Integration:** Option B (Soft Plugin / Graceful Degradation)

### Data Architecture

- **Primary DB:** SQLite (Async via `aiosqlite`)
- **Migrations:** Alembic
- **Graph Strategy:** **NetworkX + SQLite** (Hybrid). Use NetworkX for in-memory graph algorithms (path finding, prerequisite checks) and persist nodes/edges to SQLite relational tables.
- **Rationale:** Best balance of algorithm power (Python ecosystem) and simple persistence (SQLite).

### Authentication & Security

- **Service Auth:** **Static Bearer Token** (API Key).
- **Rationale:** Meets OpenAI API protocol requirements for Open WebUI client connection. Simple but effective for internal Docker network.

### API & Communication Patterns

- **Protocol:** REST (OpenAI Compatible `v1/chat/completions`)
- **Tool Execution:** **Async SSE Streaming**.
- **Rationale:** Critical for UX. Allows the user to see "Thinking..." and tool execution status updates in real-time, preventing timeouts during long chains.

### Infrastructure & Deployment

- **External Integrations:** **Soft Plugin Pattern**.
- **Rationale:** If Notion or Anki are unreachable, the service continues to function (graceful degradation), logging the error but not crashing the chat.

## 4. Implementation Patterns & Consistency Rules

### Naming Patterns

- **General Rule:** **Snake Case (`snake_case`) Everywhere**.
- **Scope:** Database tables, columns, API JSON keys, Python variables, functions, and file names.
- **Rationale:** Consistency with Python ecosystem. Simplifies Pydantic serialization for LLM tool definitions.

### Structure Patterns

- **Project Structure:** **Standard Modular Python**.
- **Tool Location:** `tools/` directory contains *only* thin wrappers (definitions & arg validation).
- **Logic Location:** Real business logic must live in `services/`.
- **Test Location:** Standard `tests/` directory (not co-located).

### Process Patterns

- **Error Handling:** **Fail Soft with Hints**.
- **Rule:** Tool functions **NEVER** raise exceptions to crash the app. They capture exceptions and return an informative error string (e.g., "Error: X failed. Hint: Try Y") to the LLM.
- **Async:** **Mandatory Async/Await**.
- **Rule:** All I/O must be async. No blocking `requests` or `time.sleep`. Use `httpx` and `asyncio.sleep`.

## 5. Project Structure & Boundaries

### Complete Project Directory Structure

```text
mentor-agent-service/
├── .env.example                # Environment variable template (API Keys, DB Path)
├── .gitignore
├── alembic.ini                 # DB Migration config
├── docker-compose.yml          # Local deployment orchestration (Service + DB Volume)
├── pyproject.toml              # Dependency management & Tool Config
├── requirements.txt            # Production dependencies
├── requirements-dev.txt        # Development dependencies (pytest, vcrpy)
├── README.md
│
├── alembic/                    # DB Migrations
│   ├── versions/
│   └── env.py
│
├── app/                        # 核心代码
│   ├── __init__.py
│   ├── main.py                 # FastAPI 入口 (App factory)
│   ├── config.py               # Pydantic Settings
│   ├── dependencies.py         # DI (DB Session, LLM Client)
│   │
│   ├── routers/                # API 路由层 (HTTP/SSE)
│   │   ├── __init__.py
│   │   ├── chat.py             # /v1/chat/completions (OpenAI Compatible)
│   │   └── health.py           # Health check
│   │
│   ├── services/               # 业务逻辑层 (Core Logic)
│   │   ├── __init__.py
│   │   ├── agent_service.py    # 核心编排 (Tool Loop)
│   │   ├── quiz_service.py     # 测验生成逻辑
│   │   └── graph_service.py    # 知识图谱算法 (NetworkX)
│   │
│   ├── repositories/           # 数据访问层 (CRUD)
│   │   ├── __init__.py
│   │   ├── user_repo.py
│   │   └── progress_repo.py
│   │
│   ├── tools/                  # LLM 工具定义层 (Definitions Only)
│   │   ├── __init__.py
│   │   ├── definitions.py      # Pydantic Models for Tool Args
│   │   └── registry.py         # Tool Map (Function -> Implementation)
│   │
│   └── utils/                  # 通用工具
│       ├── __init__.py
│       └── sse_generator.py    # OpenAI SSE 格式封装
│
├── tests/                      # 测试
│   ├── __init__.py
│   ├── conftest.py             # Fixtures (Event Loop, Async Client)
│   ├── unit/                   # 单元测试 (Mocked services)
│   ├── integration/            # 集成测试 (Real DB, Mocked LLM via VCR)
│   └── cassettes/              # VCRpy 录制的 LLM 交互
│
└── data/                       # 本地数据挂载点 (GitIgnore)
    └── mentor.db
```

### Architectural Boundaries

**API Boundaries:**
- **External:** Exposes `POST /v1/chat/completions` (OpenAI Compatible).
- **Internal:** `routers/` layer only handles HTTP/SSE protocol translation. No business logic allowed.

**Service Boundaries:**
- **Agent Service:** The central orchestrator. Maintains the conversation loop.
- **Graph Service:** Encapsulates all NetworkX logic. Other services (e.g., Quiz) must ask Graph Service for prerequisite checks, not query DB directly.

**Data Boundaries:**
- **Persistence:** Only `repositories/` can import `aiosqlite`/`sqlalchemy`. Services must use repositories.
- **Tools:** `tools/` functions must not access DB directly; they must call Services.

### Requirements to Structure Mapping

- **"Teach Me" Loop:** -> `app/services/agent_service.py` (Orchestration)
- **Knowledge Graph:** -> `app/services/graph_service.py` (Logic) + `app/repositories/graph_repo.py` (Storage)
- **OpenAI Interface:** -> `app/routers/chat.py` + `app/utils/sse_generator.py`
- **Quiz Generation:** -> `app/tools/registry.py` (Entry) -> `app/services/quiz_service.py` (Logic)

## 6. Architecture Validation Results

### Coherence Validation ✅

**Decision Compatibility:**
The selected stack (FastAPI + Async SQLite + SSE) is highly cohesive. The choice of `aiosqlite` ensures that DB operations do not block the SSE event loop, which is critical for the "Agent-as-LLM-Proxy" pattern.

**Pattern Consistency:**
The "Fail Soft" error handling pattern aligns perfectly with the LLM's need for self-correction. The ubiquitous `snake_case` naming simplifies the mapping between Python objects and JSON schemas required for tool definitions.

### Requirements Coverage Validation ✅

- **"Teach Me" Loop:** Fully supported by the Service Layer orchestration.
- **Open WebUI Integration:** Addressed via the OpenAI-compatible Router and SSE Utilities.
- **Local Privacy:** Guaranteed by the SQLite-only persistence strategy.
- **Resilience:** Handled by the Soft Plugin pattern for external integrations.

### Gap Analysis Results

**Important Gaps (To be addressed during implementation):**

1.  **Tool Status to Text Stream:** Since Open WebUI might not natively render tool execution states perfectly, the `sse_generator` must translate internal tool events (e.g., "Scanning PDF...") into user-facing text stream updates to prevent "dead air" timeouts.
2.  **Graph Visualization:** The architecture handles graph *logic*, but *visualization* will require generating Markdown/Mermaid artifacts in the chat response, as no custom UI is built.

### Architecture Readiness Assessment

**Overall Status:** READY FOR IMPLEMENTATION
**Confidence Level:** High

**Key Strengths:**
- **Simplicity:** No heavy external dependencies (Redis, Postgres) makes it easy to deploy.
- **Control:** The Custom FastAPI structure gives complete control over the LLM Context Window and Tool Loop.
- **Extensibility:** The modular `tools/` directory makes adding new capabilities (e.g., Web Search) trivial.

### Implementation Handoff

**First Implementation Priority:**
Initialize the project skeleton using the defined directory structure and install dependencies (`fastapi`, `uvicorn`, `litellm`, `aiosqlite`, `alembic`, `vcrpy`).
