# Technical Debt Registry

Items discovered during code review but deferred from immediate fix.
Each entry tracks: origin story, severity, description, and suggested fix.

## Active Items

### TD-001: graph_repo.get_topic_by_name case-sensitive matching

- **Origin**: Story 2.3 review
- **Severity**: Low
- **Description**: Story 2.3 Dev Notes specify `func.lower(Topic.name) == name.strip().lower()` inside `graph_repo.get_topic_by_name`, but the current implementation uses exact match (`Topic.name == name`). The tool layer compensates with a `get_all_topics` fallback + Python-side `.lower()` comparison, which is functionally correct but inefficient (full table scan) and inconsistent (other callers of `get_topic_by_name` don't get case-insensitive matching).
- **Impact**: Minimal for single-user scenario (few dozen topics). Becomes relevant if topics grow to hundreds or if other callers rely on case-insensitive lookup.
- **Suggested fix**: Change `graph_repo.get_topic_by_name` to use `func.lower(Topic.name) == name.strip().lower()` and remove the fallback loop in `learning_plan_tool.py` (both in `generate_learning_plan` and `get_learning_plan`).
- **Files**: `app/repositories/graph_repo.py:39`, `app/tools/learning_plan_tool.py:207-212`, `app/tools/learning_plan_tool.py:341-346`

### TD-003: Story 2.2 concept-not-found behavior vs text mismatch

- **Origin**: Story 2.2 code review follow-up
- **Severity**: High (design consistency), accepted as current behavior
- **Description**: Story text曾写明 concept 不存在时应抛 `ValueError`，当前实现在 `get_prerequisites/get_related_concepts` 返回 `[]`。团队已确认这是有意设计（查询语义以空结果表示未命中）。
- **Impact**: 主要是文档-实现口径不一致，可能让后续开发者误判为 bug。
- **Suggested fix**: 在 Story 2.2 文档中将该行为明确标注为“Accepted Deviation/Design Decision”，并在未来相关 Story 沿用相同语义。
- **Files**: `_bmad-output/implementation-artifacts/2-2-knowledge-graph-data-model-and-service.md:136`, `mentor-agent-service/app/services/graph_service.py:211`

### TD-004: concept_edges 缺少 DB 层 relationship_type CHECK 约束

- **Origin**: Story 2.2 code review follow-up
- **Severity**: Medium
- **Description**: 目前仅在 service 层校验 `relationship_type in {prerequisite, related}`；DB 层没有 `CHECK` 约束，绕过 service 写入时存在脏数据风险。
- **Impact**: 低频但真实的数据完整性风险（脚本/手工 SQL/未来新调用方可绕过校验）。
- **Suggested fix**: 在后续 migration 中为 `concept_edges.relationship_type` 增加 CHECK 约束，并补迁移回归测试。
- **Files**: `mentor-agent-service/alembic/versions/003_create_knowledge_graph_tables.py:45`, `mentor-agent-service/app/models.py:58`

### TD-005: prerequisites/related 查询结果顺序未定义

- **Origin**: Story 2.2 code review follow-up
- **Severity**: Low
- **Description**: `get_prerequisites/get_related_concepts` 返回顺序依赖图迭代顺序，未做稳定排序。
- **Impact**: 当前功能正确，但在 API/UI 或快照测试依赖顺序时会产生不稳定输出。
- **Suggested fix**: 在 service 层按 `id` 或 `name` 排序后返回；并补充顺序稳定性测试。
- **Files**: `mentor-agent-service/app/services/graph_service.py:215`, `mentor-agent-service/app/services/graph_service.py:245`

### TD-006: production 环境未隐藏 echo 诊断工具

- **Origin**: Epic 2 review follow-up / production hardening note
- **Severity**: Medium
- **Description**: `echo` 当前作为 tool-loop 诊断工具注册在公开 tool 列表中。规划文档未明确生产环境可见性策略，存在“非业务工具暴露给最终用户/模型”的边界不清问题。
- **Impact**: 功能上不阻塞，但会增加误调用与产品能力认知噪音；生产环境工具面暴露不够最小化。
- **Suggested fix**: 增加环境开关（例如 `TOOL_ENABLE_ECHO`），在 prod 默认关闭、dev/test 默认开启；并在用户手册/运维手册说明环境差异。
- **Files**: `mentor-agent-service/app/tools/__init__.py:11`, `_bmad-output/planning-artifacts/epics.md:177`

### TD-008: Legacy topic 无 plan JSON — `get_learning_plan` 启发式回退

- **Origin**: Epic 2 Issue #16 修复
- **Severity**: Low
- **Description**: Issue #16 修复后，新生成的 topic 会在 `description` 字段存储原始 JSON 结构，`get_learning_plan` 可精确还原层级。但修复前已生成的 topic（`description=None`）仍走 `_format_plan_from_db()` 启发式重建（通过名称编号前缀区分 chapter/section），可能出现层级偏差（如前言被当作 chapter 导致编号偏移）。
- **Impact**: 仅影响修复前已有的 topic。单用户场景下删除重建即可。若未来需要批量修复，可写一次性 backfill 脚本。
- **Suggested fix**: 编写 backfill 脚本：对 `description IS NULL` 的 topic，用 `_format_plan_from_db` 反推 JSON 并写入 `description`。或要求用户对旧 topic 重新生成。
- **Files**: `mentor-agent-service/app/tools/learning_plan_tool.py`

### TD-007: Provisional/Commit SSE 协议（完美方案，未来增强）

- **Origin**: Epic 2 Step 1 double-response bug 修复过程中，Codex 架构评审建议
- **Severity**: Low（直接流式方案已解决用户痛点）
- **Description**: 当前 streaming agent loop 已从 Buffer+Discard 演进为**直接流式输出**（2026-02-23 实施，详见 `docs/refactoring/direct-streaming.md`）。Content chunks 实时推送给客户端，工具调用时中间文字（如"让我查一下..."）对用户可见，`assistant_msg.pop("content", None)` 防止上下文污染。Provisional/Commit 协议是进一步的"完美方案"：可让前端在收到 `discard` 事件时清除中间文字，但需要 Open WebUI 前端配合。
- **Impact**: 当前直接流式方案的唯一 trade-off 是工具调用场景下用户会看到一小段中间文字再看到工具执行状态。实际使用中可接受（类似 ChatGPT tool use 流程）。
- **Suggested fix**: 需 Open WebUI 前端配合（非本项目控制范围），降级为未来增强。
- **Files**: `mentor-agent-service/app/services/agent_service.py`, `mentor-agent-service/app/utils/sse_generator.py`

### TD-009: LLM 绕过工具编造结果 + RAG 降级不透明

- **Origin**: Epic 2 Step 7 人工验证 → Epic 2 验收后多 KB 测试复现升级
- **Severity**: **Low**（降级于 Epic 2 回顾 2026-02-23：系统提示词强化已有效控制，近期测试中未复现；通过 Epic 3 E2E 验收中的 tool-call 验证点持续监控）
- **Description**: 发现两类 LLM 不诚实行为：
  1. **工具调用编造（Fabrication）**：多 KB 场景下，LLM 调用 `list_collections` 获取 KB 列表后，未调用 `generate_learning_plan`，而是在文本输出中伪造工具调用 UI（"🔧 Running generate_learning_plan..."）并编造完整学习计划。容器日志确认 `generate_learning_plan` 从未被调用（`finish_reason=stop`，零 tool_call），DB 无对应 topic 记录。
  2. **RAG 降级静默**：`search_knowledge_base` 返回错误字符串时，LLM 不告知用户 RAG 失败，静默用训练知识替代。
- **Impact**:
  - 用户无法区分"基于上传文档的真实结果"与"LLM 编造的内容"
  - 在专有/非公开资料场景下，编造内容可能完全错误且不可验证
  - 破坏用户对工具链的信任
- **Evidence**: 2026-02-22 容器日志 — `list_collections` 调用 2 次后 `finish_reason=stop`；后续请求全部 `finish_reason=stop` 无任何工具调用；DB 仅 1 个 topic（Python Crash Course），无 AI-Assisted Programming
- **Suggested fix**:
  1. **System prompt 强化（必须）**：明确禁止 LLM 在未调用工具的情况下声称已调用；要求在工具返回错误时如实告知用户
  2. **应用层校验（推荐）**：在 `agent_service.py` tool-loop 结束后，检测最终回答文本是否包含工具调用标记（如 "🔧 Running"）但实际 tool_call 记录中无对应调用，若检测到则注入警告
  3. **结构化输出约束（长期）**：将学习计划生成结果限制为 structured output（JSON schema），使 LLM 无法在 free-text 中绕过工具链伪造格式化输出
- **Files**: `mentor-agent-service/app/prompts/mentor_system_prompt.md`, `mentor-agent-service/app/services/agent_service.py`

### TD-011: `TOC_ANALYSIS_PROMPT` 允许无证据的推测性章节分组

- **Origin**: Epic 2 验收后 GPT 代码审查 + TD-009 讨论
- **Severity**: Low（仅在 RAG 返回无清晰目录结构的内容时触发）
- **Description**: `TOC_ANALYSIS_PROMPT` 第 22 行规则 `If no clear chapter/section structure, create logical groupings` 允许内部 LLM 在 RAG 检索文本缺少明确目录时自行编造章节结构。产出的 JSON 格式合法，会被直接存储和展示，无"证据绑定"约束（不要求每章对应原文片段）。与 TD-009 不同：TD-009 是 agent 层 LLM 绕过工具；TD-011 是工具内部 inner LLM prompt 太宽松。
- **Impact**: 工具正常调用时，若上传文档本身缺少清晰目录（如论文集、笔记），生成的学习计划可能包含凭空编造的章节划分。单一结构化教材场景下几乎不触发。
- **Suggested fix**:
  1. 收紧 prompt：将 `create logical groupings` 改为 `return an error or flag that no clear structure was found`，让调用方决定是否回退
  2. 可选：要求 inner LLM 在 JSON 中附带每章对应的原文引用片段（evidence binding），便于后续校验
- **Files**: `mentor-agent-service/app/tools/learning_plan_tool.py:22`

### TD-013: Agent 收到图片消息时长时间卡住

- **Origin**: Epic 2 验收后人工测试 (2026-02-22)
- **Severity**: Medium
- **Description**: 用户在 Open WebUI 中向 agent 发送截图时，agent 卡住超过 2 分钟无响应。推测原因：图片消息通过 claude-max-proxy 转发给 Claude API，proxy 或 LLM 处理图片的延迟显著高于纯文本；当前 agent loop 无图片消息的超时或降级处理。
- **Impact**: 用户体验差，无法分享截图进行交互式学习（如分享代码截图、错误截图等场景）。
- **Suggested fix**:
  1. **排查瓶颈**: 确认延迟发生在 proxy 层（转发图片 base64 耗时）还是 LLM API 层（处理 vision 请求耗时），通过 proxy 和 agent-service 的日志对比时间戳
  2. **超时配置**: 检查 `agent_service.py` 中 litellm `acompletion` 调用的 timeout 设置，对含图片的请求适当放宽或设置合理上限
  3. **用户反馈**: 在 SSE stream 中尽早发送 heartbeat 或处理状态提示，避免前端判定连接超时
- **Files**: `mentor-agent-service/app/services/agent_service.py`, `claude-max-proxy/server.js`

## Resolved Items

### TD-012: `generate_learning_plan` 不支持多文档 collection

- **Origin**: Epic 2 验收后人工测试 (2026-02-22)
- **Severity**: Medium
- **Resolution**: 已实施 (2026-02-23)。核心改动：
  1. **多文档检测**: `_fetch_collection_files()` 获取文件列表 → `_match_filename()` 路由到单文件/批量/歧义路径
  2. **逐文件生成**: `_generate_plan_for_file()` 用 `_query_collection_raw(k=20/40)` + `_filter_chunks_by_source()` 按 metadata 过滤 → LLM 分析 → 原子写入 DB
  3. **Stem-based 过滤**: `_stem()` + 双向包含匹配，修复了元数据无扩展名时的匹配失败
  4. **k 重试**: k=20 过滤后不足 `_MIN_CHUNKS_FOR_PLAN` 时自动重试 k=40
  5. **collection_name 改为 required**: 移除 KB auto-discovery 分支，简化流程
  6. **执行顺序重构**: idempotency check 移到 multi-doc detection 之后，避免 collection 名称命中旧 topic 导致 short-circuit
- **Files**: `app/tools/learning_plan_tool.py`, `app/tools/search_knowledge_base_tool.py`, `app/tools/__init__.py`

### TD-014: `generate_learning_plan` 幂等性阻止重新生成

- **Origin**: Epic 2 验收后人工测试 (2026-02-22)
- **Severity**: Medium
- **Resolution**: 已实施 (2026-02-23)。新增 `force: bool = False` 参数，`force=True` 时采用"先建后拆"策略（先完成 RAG+LLM+parse，成功后在同一事务中 `delete_topic_cascade` + 建新），确保 RAG/LLM 失败时旧计划完好。Tool schema 已暴露 `force` 参数。
- **Files**: `app/tools/learning_plan_tool.py`, `app/tools/__init__.py`

### TD-010: 多知识库场景下搜索范围未隔离

- **Origin**: Epic 2 验收后讨论
- **Severity**: Medium
- **Resolution**: 已实施。三项改动解决：(1) `list_collections` 输出仅名称，不暴露 UUID；(2) `search_knowledge_base` 和 `generate_learning_plan` schema 均暴露 `collection_name` 可选参数，接受人类可读名称；(3) `_resolve_collection_name_to_id()` 在工具内部做 case-insensitive name→UUID 解析。详见 `docs/refactoring/multi-kb-isolation.md`。
- **Files**: `app/tools/search_knowledge_base_tool.py`, `app/tools/learning_plan_tool.py`, `app/tools/__init__.py`

### TD-002: add_edge has local variable shadowing global _digraph

- **Origin**: Story 2.3 self-review (pre-existing, Story 2.2)
- **Severity**: Low
- **Resolution**: Already fixed — `add_edge` error handler now calls `reset_graph()` (line 193) after `load_graph()` fallback fails. Verified 2026-02-21.
- **Files**: `app/services/graph_service.py:193`
