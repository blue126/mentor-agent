# 流式输出门控优化方案

**状态**: 草案，待讨论 (2026-02-25)
**背景**: RAG Embedding A/B 测试（bge-m3 vs MiniLM）结论引发的架构思考

## 问题陈述

当前 agent-service 的流式输出有三层决策：

```
用户消息 → 关键词门控 → fast path (直接流式) | tool loop (buffer & discard)
                                                    ↓
                                              LLM 决定是否调用工具
                                                    ↓
                                              finish_reason=stop → flush
                                              finish_reason=tool_calls → discard + 执行工具
```

**核心矛盾**：
1. 关键词门控准确率不够：false positive（不需要工具却进了 tool loop）和 false negative（需要工具却走了 fast path）
2. tool loop 的 buffer & discard 导致所有走该路径的请求都无法流式输出，即使 LLM 最终没调用任何工具
3. 之前尝试过的"直接流式输出"方案（direct-streaming.md）因 double-response 问题已回退

## 关键洞察：来自 RAG A/B 测试

bge-m3 在 B1 测试中取得 Recall@5 = 100%（28/28），证明高质量 embedding 模型可以做到"一次检索就准"。这意味着：

- **LLM 不需要迭代搜索来补救检索质量** → 不需要 tool loop 的多轮调用能力
- **Open WebUI 原生 RAG pipeline 的检索质量已足够** → agent-service 不需要自己做 RAG
- **RAG 可以从 tool 调用变成 prompt context 注入** → RAG 对话可以走 fast path

这个洞察的前提是：**必须使用高质量的 embedding 模型（如 bge-m3）**。

## 当前工具清单与分类

| 工具 | 用途 | 调用频率 | 是否可外移 |
|---|---|---|---|
| `search_knowledge_base` | RAG 检索 | 高频 | ✅ 可由 Open WebUI 原生 RAG 替代 |
| `list_collections` | 列出知识库 | 低频 | ✅ 可由 Open WebUI 原生 RAG 替代（自动选择） |
| `generate_learning_plan` | 生成学习计划 | 低频 | ❌ agent-service 独有功能 |
| `get_learning_plan` | 查看学习计划 | 中频 | ❌ agent-service 独有功能 |
| `extract_concept_relationships` | 知识图谱关系提取 | 低频 | ❌ agent-service 独有功能 |
| `echo` | 测试工具 | 仅测试 | — |

RAG 相关工具（`search_knowledge_base` + `list_collections`）是高频调用，也是门控 false positive 的主要来源。其余工具（learning_plan、extract_relationships）低频且意图明确，不太会被误触发。

## 方案：分层架构 + always-stream

### 核心思路

将 RAG 从 agent-service 的 tool 调用中剥离，交给 Open WebUI 原生 RAG 处理。agent-service 保留非 RAG 工具，并采用 always-stream 模式。

```
变更前：
  Open WebUI → agent-service → 关键词门控 → fast path | tool loop (RAG + 学习计划 + 知识图谱)

变更后：
  Open WebUI (原生 RAG: bge-m3 检索 + context 注入) → agent-service (always-stream + 非 RAG 工具)
```

### 请求流转

**场景 1：普通对话（无 RAG、无工具）— 最常见**
```
Open WebUI → agent-service (stream + tools schemas)
  → LLM 不调用工具 → finish_reason=stop
  → content chunks 边收边转发 → 用户看到逐 token 流式输出
```

**场景 2：RAG 对话**
```
Open WebUI 原生 RAG pipeline:
  1. generate_queries() 改写查询
  2. bge-m3 embedding + hybrid search → Top K chunks
  3. 注入 RAG context 到 system/user message

→ agent-service 收到的是普通 chat（已含 RAG context）
→ 同场景 1：LLM 直接基于 context 回答，逐 token 流式输出
```

**场景 3：需要工具的对话（学习计划、知识图谱等）— 低频**
```
Open WebUI → agent-service (stream + tools schemas)
  → LLM 决定调用 generate_learning_plan
  → buffer & discard：缓冲已输出的 preamble
  → 执行工具 → 下一轮 LLM 生成 → flush final answer
```

### 关键设计决策

**1. always-stream + 乐观转发**

删除关键词门控。所有请求都带 tool schemas，所有 content chunks 边收边转发。

```python
async for chunk in stream_result:
    chunks.append(chunk)
    delta = chunk_dict["choices"][0].get("delta", {})
    if delta.get("content"):
        await queue.put(f"data: {json.dumps(chunk_dict)}\n\n")  # 立即转发
```

**2. tool_calls 时的 double-response 问题**

这是之前直接流式输出方案回退的核心原因（见 `direct-streaming.md`），需要正视：

**已验证的事实（2026-02-23 回退时确认）：**
- Anthropic 模型（Claude）在决定调用工具前，**会先生成一段完整的文本回答**，不是简短的过渡句，而是一段看似完整的回答
- system prompt 约束（"需要调用工具时直接调用，不要先输出文字"）**对 Anthropic 模型不可靠**——模型仍然会先输出完整文本再发 tool_calls
- 这意味着"乐观流式输出 + tool call 检测中断"方案在 Anthropic 模型上会导致用户看到一段完整回答，然后回答消失或被覆盖，又出现一段不同的回答——**体验比 buffer & discard 更差**

**结论：对于需要 tool loop 的路径，buffer & discard 仍然是当前最不坏的选择。**

**本方案的核心不是解决 double-response，而是减少需要进入 tool loop 的请求比例。** 通过将高频的 RAG 调用从 tool loop 中移除（迁移到 Open WebUI 原生 RAG），绝大多数请求不再需要工具，直接走流式输出。剩余低频的工具调用（学习计划、知识图谱）继续走 buffer & discard，用户对这类操作的延迟容忍度更高。

**3. RAG 工具迁移**

从 agent-service 移除 `search_knowledge_base` 和 `list_collections` 工具。

前提条件：
- ✅ bge-m3 embedding 已部署（B1 测试验证，Recall@5 = 100%）
- Open WebUI 的 Knowledge Base 功能已配置好（本次测试已完成）
- Open WebUI 的 Model Settings 中为 mentor 模型启用 Knowledge Base 关联

需要验证：
- Open WebUI 原生 RAG 是否支持自动选择 Knowledge Base（vs 手动选择）
- `search_knowledge_base` 工具描述中的 "Always formulate queries in English" 指令在 bge-m3 下不再需要（bge-m3 原生多语言），需要确认 Open WebUI 的 `generate_queries()` 不会做类似的语言转换
- `search_knowledge_base` 的 `k` 参数默认 8，Open WebUI 的 Top K 当前设为 5，需要统一

**4. `search_knowledge_base` 工具描述更新**

如果暂时不移除 RAG 工具（渐进迁移），至少需要更新工具描述：
- 删除 "Always formulate queries in English"（bge-m3 支持多语言）
- 这一条是 MiniLM 时代的 workaround，保留会误导 LLM

## 实施路径

### Phase 1：低风险改善（可立即执行）

1. **更新 `search_knowledge_base` 工具描述**：删除 "Always formulate queries in English"，bge-m3 原生多语言不再需要此 workaround
2. **验证**：确认 LLM 在中文查询时不再被工具描述误导为先翻译成英文

注：`always-stream-refactoring-plan.md` 中的乐观转发方案因 Anthropic 模型的 double-response 行为而**不可直接实施**。关键词门控虽不完美，但在 Phase 2 完成前仍需保留。

### Phase 2：RAG 架构简化（核心改善，需验证）

1. **验证 Open WebUI 原生 RAG 在生产场景下的表现**：不只是 A/B 测试的 Q&A，还包括多轮对话、追问链等
2. **配置 Open WebUI Model Settings**：为 mentor 模型关联 Knowledge Base，使所有对话自动触发 RAG
3. **从 agent-service 移除 RAG 工具**：删除 `search_knowledge_base` 和 `list_collections`
4. **验证**：端到端测试，确认 RAG 对话仍然正常工作

### Phase 3：进一步优化（可选）

1. 评估是否需要保留 learning_plan 和 extract_relationships 工具的 tool loop 路径
2. 如果这些工具也可以外移或低频到不影响体验，可以进一步简化 agent-service

### Phase 2 完成后的门控简化

Phase 2 移除 RAG 工具后，剩余工具（learning_plan、extract_relationships）意图明确且低频。此时可以：
- **大幅精简关键词列表**：只保留 "学习计划"、"learning plan"、"知识图谱"、"relationship"、"concept" 等少量高信号词
- 或 **保留 always-stream + buffer & discard**：所有请求都带 tools，但由于绝大多数请求 LLM 不会调用工具，`finish_reason=stop` 时直接 flush buffered content，延迟仅为 buffer 累积时间（远小于 tool 执行时间）

注：即使保留 buffer & discard，移除 RAG 工具后 false positive 大幅下降（RAG 是当前最大的 false positive 来源），门控问题的严重性显著降低。

### Phase 3：进一步优化（可选）

1. 评估是否需要保留 learning_plan 和 extract_relationships 工具的 tool loop 路径
2. 如果这些工具也可以外移或低频到不影响体验，可以进一步简化 agent-service

## 风险评估

| 风险 | 影响 | 缓解 |
|---|---|---|
| Open WebUI 原生 RAG 在复杂场景下质量下降 | 回答质量退化 | Phase 2 前充分测试；保留回退到 tool loop RAG 的能力 |
| 移除 RAG 工具后无法迭代搜索 | 单次检索不准时无法补救 | bge-m3 的高 Recall@5 是前提；如果未来切换到更差的模型需重新评估 |
| Open WebUI 自动 RAG 注入增加 LLM input tokens | 成本增加、速度下降 | 调整 Top K 和 chunk size 控制注入量 |
| Anthropic 模型的 double-response 行为 | 走 tool loop 的请求用户体验差 | Phase 2 后仅低频工具需要 tool loop，用户容忍度高；持续关注 Anthropic API 是否改善此行为 |

## 成功指标

- **延迟**：RAG 对话 TTFT < 3s（Phase 2 完成后，RAG 对话走 fast path 流式输出）
- **延迟**：普通对话 TTFT 保持 < 2s（Phase 2 后 false positive 大幅减少）
- **RAG 质量**：Open WebUI 原生 RAG 的 Recall@5 >= 当前 tool loop RAG 的水平
- **门控准确率**：false negative 为 0（仅剩的几个工具关键词覆盖率容易做到 100%）

## 与 A/B 测试结论的关系

本方案的 Phase 2（RAG 架构简化）依赖于两个前提：
1. **bge-m3 的 Go 决策**：如果 A/B 测试最终结论为 No-Go，Phase 2 不可执行
2. **高质量 embedding 模型**：方案的核心逻辑是"一次检索就准 → 不需要迭代搜索 → 不需要 tool loop"。这要求 embedding 模型的检索质量足够高。如果未来切换到更差的模型，需要重新评估

Phase 1（工具描述更新）不依赖 A/B 测试结论，可独立执行。

## 相关文档

- `docs/refactoring/always-stream-refactoring-plan.md` — always-stream 技术方案（乐观转发部分因 Anthropic double-response 行为不可直接实施，但 tool loop 逻辑可参考）
- `docs/refactoring/direct-streaming.md` — 之前的直接流式尝试（已回退 2026-02-23）及经验教训：确认 Anthropic 模型会在 tool_calls 前生成完整文本，system prompt 约束不可靠
- `docs/testing/reports/rag-ab-results-2026-02-24.md` — bge-m3 A/B 测试结果（Phase 2 的数据依据，Recall@5 = 100%）
