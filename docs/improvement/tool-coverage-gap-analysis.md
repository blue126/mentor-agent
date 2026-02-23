# Mentor Agent 工具覆盖差距分析

日期：2026-02-21
范围：`_bmad-output/planning-artifacts` 设计文档 vs 工具建议清单

## 结论

当前设计已覆盖学习主链路工具（RAG/前置检查/测验/进度/Notion/Anki），但缺少若干高频通用工具，尤其是 `web_search` 与时间类工具。这会直接影响用户对话可用性（如“今天几号”无法回答）。

## 对比结果

### 1) 已覆盖（设计中有明确工具能力）

- `search_knowledge_base`
- `check_prerequisites`
- `get_related_concepts`
- `generate_quiz`
- `grade_answer`
- `get_weak_concepts`
- `push_to_notion`
- `create_anki_card`

### 2) 部分覆盖（有需求语义，但未明确工具接口）

- `get_learning_progress`（文档有“进度可查询”诉求，但未独立定义工具）
- `update_learning_progress`（文档有 mastery 更新规则，但未独立定义工具）
- `list_collections`（代码中已存在，但规划文档未作为明确能力项）

### 3) 当前设计未覆盖（建议补入）

- `get_current_datetime`
- `convert_timezone`
- `calculator`
- `web_search`
- `fetch_url`

### 4) 高级候选（后续阶段）

- `detect_misconception`
- `schedule_review`
- `confidence_signal`
- `tool_policy_guard`

## 风险说明

- 缺少 `web_search`：无法处理时效性问题与站外事实补充。
- 缺少时间工具：高频问题（日期/时间）直接失败，降低可用性观感。
- 缺少显式 progress 工具：进度读写行为隐式分散在流程里，不利于测试与审计。

## 建议补齐顺序（仅设计层）

1. 优先补 `get_current_datetime` / `convert_timezone`。
2. 补 `web_search` + `fetch_url`（附超时/限流/Fail Soft 约束）。
3. 将 `get_learning_progress` / `update_learning_progress` 显式化为工具接口。
4. 在 Epic/PRD 中补 `list_collections` 的设计条目，保持“设计-实现”一致。
