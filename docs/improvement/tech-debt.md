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

### TD-007: Provisional/Commit SSE 协议（实时流式 + 防 double-response）

- **Origin**: Epic 2 Step 1 double-response bug 修复过程中，Codex 架构评审建议
- **Severity**: Low（当前 Buffer + Discard 方案已解决核心问题）
- **Description**: 当前 streaming agent loop 采用 Buffer + Discard 方案：每轮迭代缓冲 content chunks，`finish_reason=="stop"` 时 flush，`finish_reason=="tool_calls"` 时 discard。此方案正确性完备，但工具迭代期间用户看不到实时文本流（最终回答一次性输出）。Provisional/Commit 协议可实现"实时流式 + 正确性"兼得：
  - LLM 输出的 content chunks 标记 `provisional: true`，实时流给前端
  - `finish_reason=="stop"` → 发送 `commit` 事件，前端保留已展示内容
  - `finish_reason=="tool_calls"` → 发送 `discard` 事件，前端清除已展示内容，执行工具后继续
- **Impact**: 当前方案在多轮工具迭代场景下，用户需等待所有工具执行完毕才能看到回答文本。对于快速单轮工具调用（<2s）几乎无感知差异；对于 3+ 轮迭代可能有明显延迟感。
- **Suggested fix**: 需 Open WebUI 前端配合：
  1. SSE 事件格式扩展：新增 `provisional`、`commit`、`discard` 事件类型
  2. 前端渲染层支持：provisional 内容可渲染但标记为"可撤回"，收到 discard 时清除
  3. 后端 `agent_service.py` 改回实时 streaming，但包装为 provisional 事件
- **Blocked by**: Open WebUI 前端改造（非本项目控制范围）
- **Files**: `mentor-agent-service/app/services/agent_service.py:146-240`, `mentor-agent-service/app/utils/sse_generator.py`

## Resolved Items

### TD-002: add_edge has local variable shadowing global _digraph

- **Origin**: Story 2.3 self-review (pre-existing, Story 2.2)
- **Severity**: Low
- **Resolution**: Already fixed — `add_edge` error handler now calls `reset_graph()` (line 193) after `load_graph()` fallback fails. Verified 2026-02-21.
- **Files**: `app/services/graph_service.py:193`
