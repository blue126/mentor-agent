# Tool & Variable Naming Conventions

> LLM 工具命名规范备忘录 — 减少 LLM tool-use 参数混淆

## 核心原则

1. **LLM 可见名称保持一致** — 工具名、参数名、输出格式中的 key 应使用统一术语
2. **内部实现名称不影响 LLM** — Python 函数名、模块文件名、测试文件名可以与工具名不同
3. **参数名跨工具统一** — 同一概念在不同工具中应使用相同参数名

## 当前工具命名

| 工具名 (LLM 可见) | Python 函数 | 模块文件 | 说明 |
|---|---|---|---|
| `search_knowledge_base` | `search_knowledge_base()` | `search_knowledge_base_tool.py` | 参数: `query`, `collection_name` (optional), `k` |
| `list_collections` | `list_collections()` | `search_knowledge_base_tool.py` | 无参数 |
| `generate_learning_plan` | `generate_learning_plan()` | `learning_plan_tool.py` | 参数: `source_name`, `collection_name` (**required**), `query`, `force` |
| `get_learning_plan` | `get_learning_plan()` | `learning_plan_tool.py` | 参数: `topic_name` |
| `extract_concept_relationships` | `extract_concept_relationships()` | `extract_relationships_tool.py` | 参数: `topic_name` |
| `echo` | `echo()` | `echo_tool.py` | 测试工具；参数: `message` |

## 参数命名决策记录

### `source_name` vs `topic_name`

- `source_name` — 用于 `generate_learning_plan`，指代原始文档/书籍名称（创建时使用）
- `topic_name` — 用于 `get_learning_plan` 和 `extract_concept_relationships`，指代已存储的学习计划名称（查询时使用）
- **决定：不统一。** 语义不同：`source_name` 强调"来源材料"，`topic_name` 强调"知识图谱中的主题"
- **缓解措施：** `_PARAM_ALIASES` 在 `agent_service.py` 中将 `topic_name` → `source_name` 做软映射

### `collection_name` — Open WebUI 一致性

- Open WebUI API 使用 `collection_names` 作为 RAG 查询参数
- 工具参数统一使用 `collection_name`（单数形式，LLM 传单值更自然）
- `generate_learning_plan` 中 `collection_name` 为 **required**（Open WebUI 要求文档属于 collection，agent 总是先调 `list_collections`）
- `search_knowledge_base` 中 `collection_name` 为 optional（不指定时搜索所有 KB）
- **缓解措施：** `_PARAM_ALIASES` 将 `knowledge_base_id` / `kb_id` → `collection_name`

### `search_knowledge_base` 工具名保留

- 不改名为 `search_collection` 的原因：
  1. "knowledge base" 是用户在 Open WebUI 界面看到的概念名
  2. 改名涉及模块文件重命名 + ~80 处 mock 路径更新，风险高收益低

## 参数别名映射 (`_PARAM_ALIASES`)

位于 `agent_service.py`，在 `_execute_tool()` 中应用：

```python
_PARAM_ALIASES = {
    "topic_name": "source_name",
    "book_name": "source_name",
    "knowledge_base_id": "collection_name",
    "kb_id": "collection_name",
}
```

**维护规则：**
- 添加新工具时，检查参数名是否与现有工具一致
- 如果必须使用不同参数名，在 `_PARAM_ALIASES` 添加映射
- 别名只在目标参数存在于工具 schema 且未被显式传参时生效

## UUID 隐藏原则

**LLM 不应看到 UUID。** UUID 是 opaque 长字符串，LLM 无法忠实复制（会编造后半段）。

设计规则：
- 工具输出只显示人类可读的名称（如 `- AI-Assisted Programming`）
- 工具参数接受人类可读的名称（如 `collection_name="AI-Assisted Programming"`）
- 工具内部通过 `_resolve_collection_name_to_id()` 做 name→UUID 解析
- UUID 只在工具内部和 Open WebUI API 调用中使用，对 LLM 完全不可见

```
# 正确 — LLM 只看到名称
- AI-Assisted Programming
- Python

# 错误 — LLM 看到 UUID，会编造
- AI-Assisted Programming (collection_name: 952034a3-01ac-4814-bf5e-97bcfc4ec361)
```

## 新增工具检查清单

添加新工具时：

1. [ ] 参数名是否与现有工具中同一概念的参数名一致？
2. [ ] 输出中引用其他工具可用的值时，是否使用了目标参数名？
3. [ ] 如果参数名必须不同，是否在 `_PARAM_ALIASES` 添加了映射？
4. [ ] 工具 description 是否提到了关键参数名（帮助 LLM 正确调用）？
5. [ ] 测试文件名是否与工具名一致？（`test_{tool_name}.py`）
