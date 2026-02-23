# Issue #16: `get_learning_plan` 层级重建不一致

日期: 2026-02-22
状态: 待实施
关联: Epic 2 Story 2.3, TD-008

## 问题描述

`generate_learning_plan` 将 LLM 解析的 `[{chapter, sections}]` JSON 结构存入 DB 后，层级信息丢失 — `concepts` 表是扁平的（chapter 和 section 均为独立行）。`get_learning_plan` 用 `_is_section_name()` 启发式（检查 "1.1" 子编号模式）重建层级，但前言/序言等非编号 chapter 导致编号偏移。

### 复现

1. `generate_learning_plan` 输出: Ch 1 Getting Started, Ch 2 Variables...（正确）
2. `get_learning_plan` 输出: Ch 1-4 前言/序言/致谢, Ch 6 Getting Started...（偏移）

### 根因

- `_format_plan()`（生成路径）：直接使用 LLM 返回的 `[{chapter, sections}]` JSON → 层级精确
- `_format_plan_from_db()`（读取路径）：从扁平 concepts 用 `_is_section_name()` 启发式重建 → 非编号名称误判

## 方案：复用 `topic.description` 存储原始 JSON

`topic.description` 是已有的 nullable TEXT 字段，目前从未使用。无需 migration。

- `add_topic()` / `create_topic()` / `get_topic_by_name()` / `get_all_topics()` 已完整支持 `description` 参数
- 生成时存入 `json.dumps(parsed)` → 读取时 `json.loads(description)` → 用 `_format_plan()` 直接渲染
- Legacy topic（description=None）回退到现有启发式（参见 TD-008）

## 改动清单

### 1. `learning_plan_tool.py` — 3 处改动

**1a. 生成路径** (line ~295-300): 传 `description`

```python
topic = await graph_service.add_topic(
    session,
    normalized_name,
    description=json.dumps(parsed, ensure_ascii=False),  # 新增
    source_material=normalized_name,
    auto_commit=False,
)
```

**1b. 幂等路径** (line ~218-230): 优先用存储的 JSON

```python
if existing is not None:
    plan_text = await _resolve_plan_display(existing, session)
    ...
```

**1c. 读取路径** (`get_learning_plan`, line ~375-379): 同上

**新增辅助函数**（DRY）:

```python
async def _resolve_plan_display(topic: dict, session, *, status="Existing plan") -> str:
    """优先用 topic.description 存储的 JSON，回退到 DB 启发式重建。

    description 是 generation-time snapshot（展示快照）。
    如果未来增加 concept 编辑能力，需同步清除或更新 description，
    否则会产生 description ↔ concepts 双写漂移。
    """
    desc = topic.get("description")
    if desc:
        try:
            plan_data = json.loads(desc)
            if (
                isinstance(plan_data, list)
                and plan_data
                and isinstance(plan_data[0], dict)
                and "chapter" in plan_data[0]
            ):
                return _format_plan(topic["name"], plan_data, status=status)
        except (json.JSONDecodeError, ValueError):
            pass
    # Fallback: legacy topic without stored JSON
    concepts = await graph_service.get_concepts_by_topic(session, topic["id"])
    if not concepts:
        return f"Learning plan '{topic['name']}' exists but has no concepts yet."
    return _format_plan_from_db(topic["name"], concepts)
```

### 2. `test_learning_plan_tool.py` — 测试更新

- `TestGenerateLearningPlan`: 验证 `add_topic` 被调用时 `description` 参数包含有效 JSON
- `TestGenerateLearningPlan`: 新增 `test_idempotent_with_description_skips_format_from_db` — 幂等路径命中且 `description` 有效时，走 `_format_plan()` 而不调用 `_format_plan_from_db()`
- `TestGetLearningPlan.test_with_data`: mock `description` 含 JSON，验证输出用 `_format_plan` 而非 `_format_plan_from_db`
- 新增 `test_get_plan_description_none_fallback`: description=None 时回退到启发式
- 新增 `test_get_plan_description_invalid_json_fallback`: 损坏 JSON 时回退

### 3. 不改的文件

- `models.py` — 不改（字段已存在）
- `graph_service.py` — 不改（已支持 description 参数）
- `graph_repo.py` — 不改（已支持 description 参数）
- 无新 migration

## 验证步骤

1. `pytest tests/ -q` — 全量通过
2. 用户需删除已有 DB 数据（`docker compose down -v && docker compose up -d --build`）后重新执行 Step 3：
   - `generate_learning_plan` — 输出格式化计划
   - `get_learning_plan` — 输出**一致**的格式化计划
3. 两次输出的 chapter 结构一致

## 遗留事项

修复后新生成的 topic 会在 `description` 存储 JSON，`get_learning_plan` 可精确还原层级。但修复前已存在的 topic（`description=None`）仍走启发式回退路径（详见 TD-008）。单用户场景下删除重建即可。
