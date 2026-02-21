# 双路径架构——代码重构实施计划（初稿）

Status: Draft
日期: 2026-02-20
关联文档: [dual-path-migration-implementation-guide.md](dual-path-migration-implementation-guide.md)

## 背景

Epic 1 调试/稳定化阶段（Story 1.6）在业务代码中引入了多处 hotfix，使双路径架构在功能上可用。但这些改动以"先跑通"为目标，部分实现属于启发式 hack 或调试期遗留，需要在继续新功能开发前正式重构。

本计划与[实施指南](dual-path-migration-implementation-guide.md)互补——实施指南覆盖基础设施编排（docker-compose、容器化、env 配置），本计划覆盖业务代码层的清理与加固。

## 执行顺序

建议在实施指南步骤 1（docker-compose 更新）完成后、步骤 4（连接校验）之前执行，因为部分重构项（如 docker-compose 硬编码路径）与步骤 1 有重叠。

---

## 高优先级（迁移前提）

### R1: docker-compose.yml 硬编码宿主路径清理

- **文件:** `mentor-agent-service/docker-compose.yml`
- **现状:** `CLAUDE_AUTH_PATH` fallback 硬编码为 `/Users/weierfu/.claude`（macOS 开发机路径）
- **问题:** 跨环境不可移植，CI/CD 和其他开发者无法直接使用
- **改动:** 移除硬编码 fallback，改为纯环境变量引用或在 `.env.example` 中提供说明
- **与实施指南关系:** 步骤 1 会重构 docker-compose，可合并处理

---

## 中优先级（代码质量 & 可维护性）

### R2: `_normalize_model_for_litellm()` 路由逻辑加固

- **文件:** `mentor-agent-service/app/services/llm_service.py`
- **现状:**
  ```python
  def _normalize_model_for_litellm(model: str) -> str:
      if "/" in model:
          return model
      base_url = settings.litellm_base_url.lower()
      if "api.anthropic.com" in base_url:
          return model
      return f"openai/{model}"
  ```
- **问题:** 靠 URL 子串嗅探区分 profile——脆弱，新增上游（如 Gemini proxy）时需手动扩展条件
- **方案选项:**
  - A) 引入显式 `LLM_PROFILE` 配置变量（`subscription` / `api`），按 profile 分发（干净但多一个 env var）
  - B) 保留 URL 嗅探，但抽取为配置映射表 + 添加边界条件注释（最小改动）
- **建议:** 方案 B（最小改动原则），P2 重命名时再考虑方案 A
- **待 review 确认**

### R3: logger 配置恢复标准模式

- **文件:** `mentor-agent-service/app/services/agent_service.py`
- **现状:**
  ```python
  logger = logging.getLogger("uvicorn.error")
  logger.setLevel(logging.INFO)
  ```
- **问题:** 调试期为确保日志可见而 hack 到 `uvicorn.error`，不符合标准 logging 层级管理
- **改动:** 恢复为 `logging.getLogger(__name__)`，通过 uvicorn/logging config 统一控制日志级别
- **验证:** 重构后确认 tool-loop 诊断日志在 `docker compose logs` 中仍可见

### R4: `_TOOL_INTENT_KEYWORDS` 启发式标注

- **文件:** `mentor-agent-service/app/services/agent_service.py`
- **现状:**
  ```python
  _TOOL_INTENT_KEYWORDS = {
      "tool", "tools", "echo", "knowledge", "knowledge base", "search", "rag",
      "notion", "anki", "quiz", "practice", "graph", "progress",
      "工具", "知识库", "检索", "搜索", "题", "练习", "进度", "图谱",
  }
  ```
- **问题:** 硬编码关键词集合，新增工具时需手动同步；false negative 会导致工具请求走 fast path 跳过 tool loop
- **方案:**
  - 当前阶段：添加注释说明维护契约（"新增工具时须同步更新此集合"），标注为已知限制
  - 未来改进：考虑从 tool registry 自动提取关键词，或改用 LLM 自身判断（让 planning call 决定是否使用工具）
- **改动量:** 仅添加注释，不改逻辑

### R5: config.py 默认值与 .env.example 对齐

- **文件:** `mentor-agent-service/app/config.py`
- **现状:** `litellm_model: str = "sonnet"` — 裸模型名，依赖 `_normalize_model_for_litellm()` 运行时补前缀
- **问题:** 默认值与 `.env.example` 中的 `LITELLM_MODEL=sonnet` 一致，但与实施指南附录 A 的 `openai/claude-sonnet-4-6` 不一致
- **.env.example 当前值:** `LITELLM_MODEL=sonnet`
- **改动:** 确认 `.env.example` 和 `config.py` 默认值策略统一（裸名 + runtime normalize vs 完整名），记录决策
- **待 review 确认**

---

## 低优先级（P2 窗口）

### R6: `LITELLM_*` 全量重命名

- **范围:** ~27 个文件，~55 处引用
- **目标:** `LITELLM_BASE_URL` → `LLM_BASE_URL`，`LITELLM_KEY` → `LLM_KEY`，`LITELLM_MODEL` → `LLM_MODEL`
- **状态:** 评估报告已标注 P2，收益仅为命名一致性，当前不执行
- **触发条件:** 有合适的低风险窗口（如 Epic 间歇期），且所有 Story 测试通过

---

## 不重构的部分（确认保留）

以下 Epic 1 hotfix 经评估为合理实现，无需重构：

| 组件 | 理由 |
|---|---|
| `stream_chat_completion()` tools 参数透传 | 必要修复，实现干净，与非流式路径一致 |
| tool-loop 诊断日志（iteration/finish_reason/tool args/result） | 良好实践，对维护有持续价值 |
| `_should_use_tool_loop_for_streaming()` fast path 分流 | 架构合理（普通对话 vs 工具请求分离），逻辑清晰 |
| SSE heartbeat JSON chunk 格式 | 兼容性修复，遵循 OpenAI chunk 协议 |
| `/v1/models` 模型发现端点 | 干净实现，Open WebUI 集成必需 |
| RAG search tool + `openwebui_default_collection_names` config | 干净新增，非 hotfix |

---

## 验收标准

- [ ] 所有中优先级项已处理（实施或标注为 accepted tech debt）
- [ ] `pytest` 全量通过
- [ ] 实施指南步骤 4 连接校验通过（subscription + api 双路径）
- [ ] 无硬编码开发机路径残留
