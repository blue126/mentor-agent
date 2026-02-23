# TD-012 + TD-014: 多文档 collection 学习计划生成 + force 重新生成

**状态**: ✅ 已实施 (2026-02-23)

## Context

**TD-012**: 用户将 5 本书上传到同一个 collection "AI-Assisted Programming"。`generate_learning_plan` 执行一次 RAG 搜索，返回 5 本书的 chunks 混在一起，`TOC_ANALYSIS_PROMPT` 无法分辨来源，生成一个混乱的"四不像"学习计划。

**TD-014**: 一旦生成了质量差的计划，幂等性检查阻止重新生成。用户无法通过工具更正，只能手动操作数据库。

**目标**: 方案 C — 遍历 collection 内文档逐个生成独立学习计划，同时支持 `force` 参数重新生成。

## API 限制

- Open WebUI retrieval API (`POST /api/v1/retrieval/query/collection`) **不支持 file_id 过滤**，只能按 collection 搜索
- RAG 返回的 metadata 有 `name`/`source` 字段标识来源文件
- 应对策略：RAG 搜索后按 metadata 过滤，只取目标文件的 chunks

## 改动总览

| 文件 | 改动 |
|------|------|
| `search_knowledge_base_tool.py` | 新增 `_query_collection_raw()` |
| `graph_repo.py` | 新增 `delete_topic_cascade()` |
| `graph_service.py` | 新增 `delete_topic_cascade()` 代理 |
| `learning_plan_tool.py` | 多文档检测 + 逐文件生成 + force 参数 |
| `__init__.py` | schema 增加 `force` 参数 |
| `test_learning_plan_tool.py` | 新增多文档 + force 测试 |

## 详细设计

### 1. `search_knowledge_base_tool.py` — 新增 `_query_collection_raw()`

从 `search_knowledge_base` 中提取 HTTP POST + 响应解析逻辑为独立函数：

```python
async def _query_collection_raw(
    query: str,
    collection_names: list[str],
    k: int = 8,
) -> tuple[list[str], list[dict], list[float]] | str:
    """Low-level RAG query. Returns (documents, metadatas, distances) or error string."""
```

- 复用 `_check_api_key()` 和 `_handle_openwebui_error()`
- `search_knowledge_base` 改为调用此函数 + 格式化输出（行为不变）
- `learning_plan_tool.py` 直接调用此函数获取结构化数据

### 2. `graph_repo.py` + `graph_service.py` — cascade delete

**`graph_repo.py`** 新增：
```python
async def delete_topic_cascade(self, topic_id: int) -> None:
    """Delete topic and all its concepts + edges.

    Order: edges (any involving this topic's concepts) → concepts → topic.
    Uses OR: deletes all edges where source OR target belongs to this topic.
    This avoids dangling edge references after concepts are deleted.
    """
    concept_ids = [c["id"] for c in await self.get_concepts_by_topic(topic_id)]
    if concept_ids:
        # Delete ALL edges involving this topic's concepts (OR)
        # Must delete before concepts to avoid FK violations and dangling refs
        await self._session.execute(
            delete(ConceptEdge).where(
                or_(
                    ConceptEdge.source_concept_id.in_(concept_ids),
                    ConceptEdge.target_concept_id.in_(concept_ids),
                )
            )
        )
        await self._session.execute(
            delete(Concept).where(Concept.topic_id == topic_id)
        )
    await self._session.execute(
        delete(Topic).where(Topic.id == topic_id)
    )
    await self._session.flush()
```

**注意**: 删除条件用 OR（source 或 target 属于该 topic），确保删除 concepts 后不会留下悬挂引用的边。跨 topic 的边会被一并清除——这是正确行为，因为 concept 本身已不存在。

**`graph_service.py`** 新增代理函数：
```python
async def delete_topic_cascade(session, topic_id: int, *, auto_commit: bool = True) -> None:
```

**无需 DB migration** — 使用现有 Topic/Concept/ConceptEdge 表结构。

### 3. `learning_plan_tool.py` — 核心改动

#### 3a. 新增 `force: bool = False` 参数

```python
async def generate_learning_plan(
    source_name: str,
    query: str | None = None,
    collection_name: str = "",   # required (schema enforced)
    force: bool = False,
) -> str:
```

> **实施偏差**: `collection_name` 从 optional 改为 required。Open WebUI 要求所有文档属于 collection，
> agent 总是先调 `list_collections` 获取 collection 名称。KB auto-discovery 分支已移除。

**force=True 安全策略 — "先建后拆"（非"先删后建"）:**

```python
# 幂等性检查（修改后）
if existing is not None:
    if not force:
        return "already exists ..."  # 现有行为不变
    # force=True: 记录旧 topic_id，但先不删除
    old_topic_id = existing["id"]
    # 继续执行 RAG → LLM → parse
    # 只有 parse 成功后，在 DB 写入事务中：
    #   1. delete_topic_cascade(old_topic_id)
    #   2. add_topic + add_concepts
    #   3. commit
    # 如果 RAG/LLM/parse 任一步失败，旧数据完好
```

这样保证：RAG/LLM/parse 失败时旧计划不丢失；只有新结果就绪后才在同一事务中替换。

#### 3b. 多文档检测与路由

在 KB discovery 之后、RAG 搜索之前，插入多文档检测逻辑：

```python
# 解析出 collection UUID 后:
files = await _fetch_collection_files(collection_uuid)

# Fail Soft: files 接口失败 → 明确报错，不回退到混合 RAG
if isinstance(files, str):
    return (
        "Error: Cannot list documents in this collection — "
        "per-document plan generation is temporarily unavailable. "
        "Hint: Retry later or check Open WebUI files endpoint availability."
    )

if isinstance(files, list) and len(files) > 1:
    filenames = _extract_filenames(files)

    matched = _match_filename(source_name, filenames)
    if isinstance(matched, list):
        # 歧义：多个文件匹配 → 返回候选列表让用户选
        return _format_ambiguous_matches(source_name, matched)
    elif isinstance(matched, str):
        # 单文件模式
        return await _generate_plan_for_file(...)
    else:
        # 无匹配 → 批量模式
        return await _generate_plans_batch(...)
elif isinstance(files, list) and len(files) == 1:
    # 单文件 → 现有行为不变
    ...
```

**关键变更**: files 接口失败时不再退化为旧的混合 RAG 行为，而是明确报错并提示用户指定文件名。避免重新引入 TD-012 的混乱问题。

#### 3c. 新增 `_match_filename(source_name, filenames)` — 含歧义检测

```python
def _match_filename(source_name: str, filenames: list[str]) -> str | list[str] | None:
    """Match source_name against filenames.

    Returns:
        str — 唯一匹配的文件名
        list[str] — 多个候选（歧义）
        None — 无匹配
    """
    normalized = source_name.strip().lower()

    # Pass 1: 精确匹配（含/不含扩展名）
    exact = []
    for fname in filenames:
        if fname.strip().lower() == normalized:
            return fname  # 完全匹配，直接返回
        stem = fname.rsplit(".", 1)[0].strip().lower() if "." in fname else fname.strip().lower()
        if stem == normalized:
            exact.append(fname)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return exact  # 歧义

    # Pass 2: 子串匹配 — 收集所有候选
    candidates = [f for f in filenames if normalized in f.strip().lower()]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        return candidates  # 歧义

    return None
```

**歧义处理**: 如 `source_name="git"` 同时匹配 "Pro Git.pdf" 和 "Git in Practice.pdf"，返回候选列表，由调用方格式化为用户提示。

#### 3d. 新增 `_generate_plan_for_file()` — 单文件生成核心

```python
async def _generate_plan_for_file(
    filename: str,
    collection_uuid: str,
    query: str | None,
    force: bool,
) -> str:
```

流程：
1. **Topic 命名**: `_clean_filename(filename)` — 去扩展名 + 去重检测
2. **幂等性**: 检查是否已有同名 topic；force=True → 记录 `old_topic_id`（不立即删除）
3. **RAG 搜索**: `_query_collection_raw(query=..., collection_names=[collection_uuid], k=20)`
   - k 提高到 20（多文档场景下保证目标文件有足够 chunks 命中）
   - query 偏向性检索: `f"table of contents chapters {clean_name}"`
4. **Metadata 过滤**: `_filter_chunks_by_source(docs, metas, dists, filename)`
   - 匹配逻辑: metadata `name`/`source` 字段与 filename 做 case-insensitive 包含匹配
5. **最低阈值**: 过滤后 chunks < `_MIN_CHUNKS_FOR_PLAN (2)` → 跳过并标记
6. **LLM 分析**: `TOC_ANALYSIS_PROMPT` on 过滤后文本
7. **DB 写入（原子事务）**:
   - 如有 `old_topic_id` → `delete_topic_cascade(old_topic_id, auto_commit=False)`
   - `add_topic` + `add_concepts`（auto_commit=False）
   - `session.commit()` — 删旧 + 建新在同一事务中
8. **返回**: 格式化的学习计划

#### 3e. 新增 `_generate_plans_batch()` — 批量生成

```python
async def _generate_plans_batch(
    filenames: list[str],
    collection_uuid: str,
    query: str | None,
    force: bool,
    collection_display_name: str,
) -> str:
```

流程：
1. **限制**: `_MAX_BATCH_FILES = 10`，超出截断并提示
2. **串行逐文件处理**: 依次调用 `_generate_plan_for_file()`，每文件内执行 RAG (k=20, filename-biased query) + metadata 过滤 + LLM 分析 + DB 写入
   - 串行避免并发压力，单用户场景下性能足够
4. **per-file 隔离（hard requirement）**: 单文件的 RAG 超时/失败/LLM 失败/parse 失败均不阻塞其他文件，标记该文件为 ❌ 并继续处理下一本
5. **per-file 幂等性**: 检查各文件的 topic 是否已存在
6. **Topic 去重**: 如两个文件 `_clean_filename` 后同名，第二个加 `(2)` 后缀
6. **汇总输出**:
```
📚 Generated learning plans for collection "AI-Assisted Programming":

✅ Pro Git — 10 chapters, 28 sections
✅ The Pragmatic Programmer — 8 chapters, 22 sections
⏭️ Tidy First — already exists (use force=true to regenerate)
❌ A Philosophy of Software Design — insufficient content found

Use get_learning_plan(topic_name="Pro Git") to view details.
```

#### 3f. 新增辅助函数

```python
def _clean_filename(filename: str) -> str:
    """Remove file extension for use as topic name. 'Pro Git.pdf' → 'Pro Git'"""

def _filter_chunks_by_source(
    docs: list[str], metas: list[dict], dists: list[float], target_filename: str
) -> tuple[list[str], list[dict], list[float]]:
    """Filter RAG chunks where metadata name/source matches target_filename.
    Case-insensitive containment match on both name and source fields."""

def _format_ambiguous_matches(source_name: str, candidates: list[str]) -> str:
    """Format ambiguous match error with candidate list for user selection."""
```

### 4. `__init__.py` — schema 更新

`generate_learning_plan` schema 增加 `force` 参数：

```python
"force": {
    "type": "boolean",
    "description": (
        "Set to true to delete an existing learning plan and regenerate it. "
        "Use when the previous plan was incorrect or needs updating."
    ),
    "default": False,
},
```

### 5. 测试 — `test_learning_plan_tool.py`

#### 新增测试

| 测试 | 描述 |
|------|------|
| **多文档批量** | |
| `test_multi_doc_batch_generates_per_file` | 3 文件 collection → 为每个文件生成独立 topic |
| `test_multi_doc_source_name_matches_file` | source_name 匹配文件名 → 只生成该文件的 plan |
| `test_multi_doc_source_name_ambiguous` | source_name 匹配多个文件 → 返回候选列表 |
| `test_multi_doc_skip_existing` | 已有 topic 的文件被跳过 |
| `test_multi_doc_force_regenerate` | force=True → 先建后拆，原子替换 |
| `test_multi_doc_insufficient_chunks_skip` | 过滤后 chunks 不足 → 跳过该文件 |
| `test_multi_doc_batch_limit` | >10 文件 → 截断并提示 |
| `test_multi_doc_files_api_failure_reports_error` | files 接口失败 → 明确报错（不回退混合 RAG） |
| **force 参数** | |
| `test_force_single_doc_build_then_replace` | 单文档 force=True → 先生成新结果，再原子替换 |
| `test_force_rag_failure_preserves_old` | force=True + RAG 失败 → 旧计划完好 |
| `test_force_llm_failure_preserves_old` | force=True + LLM 失败 → 旧计划完好 |
| **辅助函数** | |
| `test_match_filename_exact` | 精确匹配 |
| `test_match_filename_without_extension` | 去扩展名匹配 |
| `test_match_filename_substring_unique` | 唯一子串匹配 |
| `test_match_filename_substring_ambiguous` | 子串匹配到多个 → 返回 list |
| `test_clean_filename` | 去扩展名 |
| `test_clean_filename_dedup` | 同名文件加后缀 |
| `test_filter_chunks_by_source` | metadata 过滤逻辑 |
| **批量隔离** | |
| `test_multi_doc_single_file_failure_continues` | 某文件 RAG 失败 → 标记 ❌ 继续处理其他文件 |
| `test_multi_doc_single_file_llm_failure_continues` | 某文件 LLM 失败 → 标记 ❌ 继续处理其他文件 |
| **cascade delete** | |
| `test_delete_topic_cascade_removes_all` | 删除 topic + concepts + 所有涉及的 edges |
| `test_delete_topic_cascade_cleans_cross_topic_edges` | 跨 topic 边也被清除（避免悬挂引用） |
| `test_delete_topic_cascade_no_concepts` | topic 无 concepts 时不报错 |

#### 现有测试影响

- `test_success_path` — 需要额外 mock `_fetch_collection_files` 返回单文件
- `test_idempotent_existing_topic` — 不变（force 默认 False）
- 其他传了 `collection_name` 的测试 — 需要 mock `_fetch_collection_files`

## 不改的文件

- `agent_service.py` — 不改（`_TOOL_INTENT_KEYWORDS` 不涉及 force 参数）
- `mentor_system_prompt.md` — 不改
- `models.py` — 不改（无需 migration）
- `search_knowledge_base` 对外行为不变（内部改为调用 `_query_collection_raw`）

## 执行顺序

1. **Step 1**: `graph_repo.py` + `graph_service.py` — cascade delete + 测试
2. **Step 2**: `search_knowledge_base_tool.py` — `_query_collection_raw()` 提取 + 验证现有测试不破
3. **Step 3**: `learning_plan_tool.py` — force 参数 + 多文档检测 + 逐文件生成
4. **Step 4**: `__init__.py` — schema 更新
5. **Step 5**: 新增测试
6. **Step 6**: `pytest tests/ -q` 全量通过

## 验证

1. `pytest tests/ -q` — 全量通过
2. Host 重建后人工验证：
   - 单文档 collection 行为不变
   - 多文档 collection → 每本书生成独立计划
   - `force=true` → 先建后拆，旧计划安全替换
   - files 接口故障 → 明确报错，不回退混合 RAG
3. 边界验证：
   - source_name 歧义匹配 → 返回候选列表
   - Topic 名碰撞 → 自动加后缀

## Review 修订记录

| 原方案 | 问题 | 修订 |
|--------|------|------|
| force=True 先删旧 topic 再生成 | RAG/LLM 失败会丢失旧计划 | **先建后拆**: 先完成 RAG+LLM+parse，成功后在同一事务中删旧建新 |
| k=15 做 RAG + metadata 过滤 | top-k 被其他书占满，目标文件可能不足 | k 提高到 **20**；query 含 filename 偏向性检索 |
| `_match_filename` 子串匹配返回第一个 | "git" 可能误命中多个文件 | 子串匹配收集**所有候选**，多候选时返回歧义列表 |
| files API 失败退化到旧混合 RAG | 重新引入 TD-012 混乱问题 | **明确报错**并提示用户指定文件名 |
| `_clean_filename` 可能碰撞 | 同名不同扩展/版本 | 碰撞时加 `(2)` 后缀 |
| RAG 并行无并发限制 | 可能打满 Open WebUI | 改为**串行逐文件处理**，避免并发压力 |
| cascade delete 边删除策略 | AND 会留下悬挂引用（concept 已删但边还在） | 用 **OR** 删除所有涉及该 topic concepts 的边，消除悬挂引用 |
| files API 失败提示文案 | "指定 source_name" 在 API 挂掉时无意义 | 改为"暂时不可用，请稍后重试或检查 files 接口" |
| 批量模式单文件失败 | 未明确隔离策略 | **hard requirement**: 单文件失败标记 ❌ 继续下一本，不拖全局 |

## 实施后追加修订 (2026-02-23)

| 原方案 | 问题 | 修订 |
|--------|------|------|
| `collection_name` optional + KB auto-discovery | Open WebUI 要求文档属于 collection，agent 总是先调 `list_collections`；auto-discovery 增加复杂度且导致 idempotency 顺序 bug | `collection_name` 改为 **required**，移除整个 auto-discovery 分支 |
| Idempotency check 在 multi-doc detection 之前 | `source_name="AI-Assisted Programming"` 命中旧 stale topic → short-circuit 返回旧计划，永远不进入 multi-doc 流程 | Idempotency check 移到 **multi-doc detection 之后**，multi-doc 路径各有自己的 per-file idempotency |
| `_filter_chunks_by_source` 用 `target_lower in name_lower` | 元数据 name 无 .pdf 扩展名时匹配失败 | 改为 **stem-based 双向包含匹配** + `_stem()` helper |
| k=20 固定 | 多文档 collection 中目标文件 chunks 可能排在 top-20 之外 | **k 重试**: k=20 不足 `_MIN_CHUNKS_FOR_PLAN` 时自动重试 k=40 |
| 批量去重后 `clean_name` 用于 RAG query | `clean_name` 可能带 `(2)` 后缀，污染搜索词 | 分离 `original_stem`（RAG query）和 `topic_name`（DB 存储） |
