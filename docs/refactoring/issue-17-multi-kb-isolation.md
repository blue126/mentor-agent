# 多知识库隔离：name→UUID 解析 + schema 暴露 collection_name

日期: 2026-02-22
状态: **已实施**
关联: TD-010 (resolved), Epic 2 验收后硬化

## 问题描述

Epic 2 验收后多 KB 测试暴露两个问题：

1. **UUID 编造**：`list_collections` 返回 UUID 给 LLM 后，LLM 无法忠实复制长 UUID（首段正确，后半段编造）
2. **跨库污染**：`search_knowledge_base` schema 不暴露 `collection_name`，LLM 直接调用时 auto-discover 搜索所有 KB

### 根因链路（修复前）

```
LLM 调用 list_collections → 返回 "- Python (ID: 952034a3-...)"
用户选 "Python" → LLM 传 collection_name="952034a3-b071-..."（UUID 编造）
→ Open WebUI 找不到该 UUID → 搜索失败或搜全库
```

## 实施方案：UUID 隐藏 + name→UUID 内部解析

### 设计原则

- **LLM 不应看到 UUID** — UUID 是 opaque 长字符串，LLM 无法忠实复制（详见 `docs/improvement/naming-conventions.md`）
- **工具接受人类可读名称** — `collection_name="AI-Assisted Programming"`
- **内部解析** — `_resolve_collection_name_to_id()` 做 case-insensitive name→UUID 映射
- **Fail Soft** — 解析失败时 name 作为 UUID pass-through（向后兼容）

### 交互流程（实际）

```
用户: "根据我上传的 Python 教材生成学习计划"
LLM → list_collections()
     → 返回 "- AI-Assisted Programming\n- Python"  # 仅名称，无 UUID

LLM 转述给用户 → 用户选 "Python"
LLM → generate_learning_plan(source_name="Python Crash Course", collection_name="Python")

[工具内部]
1. _resolve_collection_name_to_id("Python") → UUID "abc-123"
2. search_knowledge_base(query=..., collection_name="abc-123", k=8)
3. 精确搜索单 KB → 正常生成
```

## 已实施改动

### 1. `search_knowledge_base_tool.py` — `_resolve_collection_name_to_id()`

```python
async def _resolve_collection_name_to_id(name: str) -> str | None:
    """Case-insensitive name→UUID resolution. Returns None if not found."""
    items = await _fetch_knowledge_base_items()
    if isinstance(items, str):
        return None
    normalized = name.strip().lower()
    for item in items:
        if isinstance(item, dict) and item.get("name", "").strip().lower() == normalized:
            return item.get("id")
    return None
```

### 2. `list_collections` — 输出仅名称

```python
# 修复前: "- Python (ID: 952034a3-01ac-4814-bf5e-97bcfc4ec361)"
# 修复后: "- Python"
lines.append(f"- {name}")
```

### 3. `search_knowledge_base` — schema 暴露 `collection_name` + 内部 resolution

- Schema 新增 `collection_name` 可选参数（type: string）
- 函数入口处对 `collection_names` 列表逐个做 name→UUID 解析
- 解析失败 → name pass-through（可能是直接传的 UUID）
- 整个 resolution 块包裹在 try/except 中（Fail Soft）

### 4. `generate_learning_plan` — name→UUID resolution

- 多 KB 时返回列表（仅名称），让 LLM 问用户选择
- 用户选择后 LLM 传 `collection_name="Python"` → 内部 resolve 为 UUID
- 单 KB 自动使用，无额外交互

### 5. KB discovery 输出格式统一

所有向 LLM 展示的 KB 列表只显示名称，不显示 UUID。

## 测试覆盖

| 测试 | 文件 | 验证内容 |
|------|------|---------|
| `test_search_resolves_name_to_uuid` | `test_search_knowledge_base.py` | name→UUID 解析成功 → API 收到 UUID |
| `test_search_resolution_failure_passes_through` | `test_search_knowledge_base.py` | 解析失败 → name 原样传递 |
| `test_multi_kb_returns_list` | `test_learning_plan_tool.py` | 多 KB → 返回名称列表 |
| `test_single_kb_auto_select` | `test_learning_plan_tool.py` | 单 KB → 自动使用 UUID |
| `test_explicit_collection_name_bypasses_discovery` | `test_learning_plan_tool.py` | 显式传名称 → 跳过发现 |
| `test_list_collections_*` | `test_list_collections.py` | 输出仅名称，无 UUID |

## 被否决的替代方案

| 方案 | 否决原因 |
|------|---------|
| 向 LLM 暴露 UUID | LLM 无法忠实复制长 UUID（首段正确，后半段编造） |
| 会话绑定 collection_id | 引入有状态工具，违背 Fail Soft 无状态设计 |
| source_name vs 文档一致性校验 | 匹配精度不可控，不如让用户明确选择 |
| 不改 `search_knowledge_base` schema | LLM 并行调用时无法传 collection_name → 跨库污染 |
