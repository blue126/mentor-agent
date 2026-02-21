# 代码重构计划（R2-R5 + 前置修复）

Status: Draft → Ready for execution
日期: 2026-02-21
关联文档: [dual-path-migration-implementation-guide.md](dual-path-migration-implementation-guide.md)

## Context

Epic 1 调试期（Story 1.6）引入了多处 hotfix 使双路径架构可用。基础设施迁移（claude-max-proxy 容器化）已完成。本次重构清理代码质量问题，确保在继续 Story 2-2 开发前代码基线稳定。

**紧急发现**：`.env` 新增的 `CLAUDE_TOKENS_PATH` / `CLAUDE_AUTH_PATH`（docker-compose 变量）导致 pydantic-settings 报 `extra_forbidden` 错误，**所有测试当前无法运行**。

## 执行步骤

### Step 0：修复 pydantic-settings extra fields（阻塞项）

**文件**：`mentor-agent-service/app/config.py:22`

```python
# 当前
model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
# 改为
model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}
```

- 原因：`.env` 包含 docker-compose 专用变量（`CLAUDE_TOKENS_PATH`、`CLAUDE_AUTH_PATH`），app 不需要它们
- 行为变更：无（已声明字段不受影响）
- 测试影响：**解除测试阻塞**

### Step 1（R5）：config.py 默认值对齐

**文件**：`mentor-agent-service/app/config.py:6`

```python
# 当前
litellm_base_url: str = "http://litellm-claude-code:4000/v1"
# 改为
litellm_base_url: str = "http://claude-max-proxy:3456/v1"
```

- 原因：默认值指向已降级为 fallback 的旧服务，应与 `.env.example` 一致
- 行为变更：仅影响无 `.env` 时的零配置启动（旧默认本来也不可用）
- 测试影响：无（测试 mock settings）

### Step 2（R2）：`_normalize_model_for_litellm()` 加固

**文件**：`mentor-agent-service/app/services/llm_service.py:11-19`

- 提取 `"api.anthropic.com"` 为命名常量 `_DIRECT_API_URL_MARKERS`
- 添加 docstring 说明双路径逻辑和 P2 迁移方向
- **不改函数签名和返回值**

### Step 3（R3）：logger 恢复标准模式

分两步：

**A. `mentor-agent-service/app/main.py`**：添加 `logging.getLogger("app").setLevel(logging.INFO)`
- 确保 `app.*` 子 logger 的 INFO 级日志传播到 uvicorn 的 root handler

**B. `mentor-agent-service/app/services/agent_service.py:24-25`**：
```python
# 当前
logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.INFO)
# 改为
logger = logging.getLogger(__name__)
```

- 行为变更：日志中 logger 名从 `uvicorn.error` 变为 `app.services.agent_service`
- 验证：docker compose logs 中确认 tool-loop 诊断日志仍可见

### Step 4（R4）：`_TOOL_INTENT_KEYWORDS` 维护标注 + 测试修复

**A. `agent_service.py:28`**：在 `_TOOL_INTENT_KEYWORDS` 上方添加维护契约注释

**B. 修复预先存在的测试错误**（关键发现）：

Story 1.6 添加了 `_should_use_tool_loop_for_streaming()` 关键词门控，但未更新 Story 1.4 的流式测试。以下测试使用的消息不含工具关键词，导致走了 fast path 而非预期的 tool-loop path：

| 文件 | 行 | 当前消息 | 修复后消息 |
|---|---|---|---|
| `test_agent_service_streaming.py` | 192 | `"Loop"` | `"Loop the echo tool"` |
| `test_agent_service_streaming.py` | 224 | `"Crash"` | `"Use the echo tool"` |
| `test_agent_service_streaming.py` | 270 | `"Hi"` | `"Search for something"` |
| `test_agent_service_streaming.py` | 301 | `"Bad JSON"` | `"Use echo tool"` |
| `test_agent_service_streaming.py` | 350 | `"Hi"` | `"Search for something"` |
| `test_agent_service.py` | 303 | `"Hi"` | `"Search for something"` |

另外 `test_agent_service_streaming.py:354` 检查心跳格式 `": keepalive\n\n"`，但 `make_heartbeat_event()` 已改为 JSON chunk 格式——需要更新断言。

## 不重构的部分（确认保留）

| 组件 | 理由 |
|---|---|
| `stream_chat_completion()` tools 参数透传 | 必要修复，实现干净 |
| tool-loop 诊断日志内容 | 良好实践，对维护有持续价值 |
| `_should_use_tool_loop_for_streaming()` fast path 分流 | 架构合理 |
| SSE heartbeat JSON chunk 格式 | 兼容性修复，遵循 OpenAI chunk 协议 |
| `/v1/models` 模型发现端点 | 干净实现，Open WebUI 必需 |
| LITELLM_* 全量重命名 | P2，当前不执行 |

## 关键文件

- `mentor-agent-service/app/config.py` — Step 0 + Step 1
- `mentor-agent-service/app/services/llm_service.py` — Step 2
- `mentor-agent-service/app/main.py` — Step 3a
- `mentor-agent-service/app/services/agent_service.py` — Step 3b + Step 4a
- `mentor-agent-service/tests/unit/test_agent_service_streaming.py` — Step 4b
- `mentor-agent-service/tests/unit/test_agent_service.py` — Step 4b

## 验证

1. `cd mentor-agent-service && python -m pytest tests/ -v` — 全量通过
2. 宿主机 `docker compose up -d --force-recreate agent-service`，发送工具请求，确认 `docker compose logs` 中出现 `app.services.agent_service - tool-loop(stream)` 日志
3. curl `/v1/chat/completions` echo 工具调用通过
