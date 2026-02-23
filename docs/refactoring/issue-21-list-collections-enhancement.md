# Issue #21: `list_collections` 增强 — 展示 collection 内文档列表

**状态**: 已实施 ✅

## Context

用户将 5 本相关书籍上传到同一个 collection "AI-Assisted Programming"。LLM 调用 `list_collections` 后只看到 collection 名称，无法得知内部有哪些文档，于是把 collection 名"AI-Assisted Programming"当成一本书的名字。

根因：`list_collections` 只调用 `GET /api/v1/knowledge/`（列表接口），仅返回 collection 名称。需要额外调用文件列表接口获取文档名。

## API 调研结果

对 Open WebUI 0.8.3 实际测试：

| 端点 | 状态 | 说明 |
|------|------|------|
| `GET /api/v1/knowledge/{id}` | `files: null` | 详情端点不填充 files 字段 |
| `GET /api/v1/knowledge/{id}/files` | **可用** | 返回 `{"items": [...], "total": N}`，每个 item 有 `filename` 字段 |
| `GET /api/v1/files/` | 可用但全局 | 返回所有文件，不按 collection 过滤 |

选择 `GET /api/v1/knowledge/{id}/files` 作为唯一数据源。

## 输出格式

```
Available collections:
- AI-Assisted Programming (5 documents)
    • The Pragmatic Programmer - 20th Anniversary Edition (...).pdf
    • A Philosophy of Software Design, 2nd Edition (...).pdf
    • Tidy First A Personal Exercise in Empirical Software Design (...).pdf
    • TEST-DRIVEN DEVELOPMENT BY EXAMPLE (...).pdf
    • Pro Git (Scott Chacon, Ben Straub) (...).pdf
- Python (1 documents)
    • Python Crash Course, 3rd Edition (...).pdf
```

Fail Soft 退化：
```
- AI-Assisted Programming
```

## 改动

### 1. `search_knowledge_base_tool.py`

- **新增 `_fetch_collection_files(collection_id)`**: 调用 `GET /api/v1/knowledge/{id}/files`，返回 `list[dict]`。兼容 paginated (`{items: [...]}`) 和 plain list (`[...]`) 两种响应格式。
- **新增 `_extract_filenames(files)`**: 从文件列表提取文件名（`filename` → `name` → `meta.name` 优先级）。
- **增强 `list_collections()`**: 用 `asyncio.gather` 并行获取各 collection 的文件列表；输出 collection 名 + 文档名；截断上限 `_MAX_FILES_DISPLAY = 10`。

### 2. `__init__.py` — schema 描述更新

```python
"description": (
    "List all available collections and their documents. "
    "Returns collection names with document filenames."
),
```

### 3. 测试 — `test_list_collections.py`（17 个）

- 正常路径：list format、paginated format、plain list format
- 多文档：5 documents 格式验证
- 截断：15 files → 显示 10 + `...and 5 more`
- Fail Soft：files endpoint 失败、unexpected format、empty files
- 备用字段：`name` / `meta.name` 提取
- 原有 Fail Soft（list 接口级别）：unreachable、timeout、401、500、generic、malformed、empty key、auth header

### 4. Integration 测试修复（附带）

修复了 3 类预存的 integration 测试问题（共 11 个测试）：
- **Alembic 路径**（7 个）：`script_location` 相对路径 → `set_main_option` 绝对路径
- **API key 未 mock**（2 个）：补充 `_fetch_knowledge_base_items` / `settings` mock
- **System prompt 路径**（2 个）：补充 `prompt_service.settings` mock

## 验证

1. `pytest tests/ -q` — 259 passed ✅
2. Host rebuild 后人工验证：LLM 正确列出 collection 名 + 5 本书名 ✅
3. Fail Soft: files endpoint 故障时退化为仅 collection 名 ✅
