# RAG Embedding 更换 A/B 测试方案（可执行版）

版本: v3.0  
目标: 用同一批问题和同一批文档，验证 `all-MiniLM-L6-v2` 与 `bge-m3` 的实际效果差异，得到可上线结论。

## 1) 测试范围与结论门槛

- 范围: Open WebUI RAG 路径（检索 + 回答）。
- 对照组 A: `all-MiniLM-L6-v2`。
- 实验组 B: `bge-m3`。
- 判定策略: `Phase 1` 为硬门槛，`Phase 2` 为稳健性门槛（不允许明显退化）。
- 上线门槛（同时满足）:
  - B 的 `Recall@5` >= 80%
  - B 的 `Top1 Hit` >= 60%
  - `Recall@5` 提升: `(B - A) / A >= 15%`
  - `Top1 Hit` 提升: `(B - A) / A >= 10%`
  - B 的回答人工评分均分 >= 4.2/5
  - B 的 P95 总延迟 <= A 的 P95 x 1.2
  - Phase 2 中 B 的连续证据命中退化题数 < 3（即 >= 3 题连续退化则 No-Go）

## 2) "同一 chunk" 的具体含义

做 A/B 时，除了 embedding 模型，其他条件必须一致。

"同一 chunk" 指以下参数在 A/B 两轮完全相同:

- `Chunk Size`: 固定为 `900`
- `Chunk Overlap`: 固定为 `200`
- `Top K`: 固定为 `5`
- `Hybrid Search`: 固定为 `ON`
- `RAG Query Generation Template`: 固定为同一版本
- 文档集合: 同一批文件、同一版本、同一上传顺序

如果这几个参数不一致，结果不能归因于 embedding 模型。

## 3) 环境准备（一次性）

### 3.1 分阶段文档清单（先一致，再多样化）

本方案采用两阶段：

- `Phase 1（主评测，70%权重）`: 文档尽量一致，用于严格 A/B 对比。
- `Phase 2（泛化评测，30%权重）`: 文档风格尽量不同，用于验证稳健性。

### Phase 1 书单（固定，不允许变更）

- A Philosophy of Software Design, 2nd Edition
- Pro Git
- TEST-DRIVEN DEVELOPMENT BY EXAMPLE（txt）
- The Pragmatic Programmer - 20th Anniversary Edition
- Tidy First: A Personal Exercise in Empirical Software Design

在测试记录中维护文档清单表（示例）:

| doc_id | 文件名 | 版本标识 | 备注 |
| --- | --- | --- | --- |
| D01 | A Philosophy of Software Design ... .pdf | v2026-02-24 | 英文，设计思想 |
| D02 | Pro Git ... .pdf | v2026-02-24 | 英文，Git |
| D03 | TEST-DRIVEN DEVELOPMENT BY EXAMPLE ... .txt | v2026-02-24 | 英文，TDD |
| D04 | The Pragmatic Programmer ... .pdf | v2026-02-24 | 英文，工程实践 |
| D05 | Tidy First ... .pdf | v2026-02-24 | 英文，重构策略 |

### Phase 2 书单（固定新增）

在 Phase 1 基础上，固定新增以下两本（本轮评测按这两本执行）：

| doc_id | 文件名 | 版本标识 | 备注 |
| --- | --- | --- | --- |
| D06 | IPv6 - Silvia Hagen.pdf | v2026-02-24 | 英文，网络协议 |
| D07 | 我的奋斗 罗永浩著(文字版).pdf | v2026-02-24 | 中文，叙事类 |

可选扩展（不纳入本轮必测）:

- D08: 额外英文技术文档（如 RFC）
- D09: 额外中文技术文档（如命令手册/博客）

### 3.2 固定 Open WebUI RAG 参数

由 Agent 通过 API 设置并验证（见第 13 节 API Reference）:

- Chunk Size = 900
- Chunk Overlap = 200
- Top K = 5
- Hybrid Search = ON
- RAG Query Generation Template = 固定模板

Agent 调用 `GET /api/v1/retrieval/config` 获取当前配置，如有不一致则调用 `POST /api/v1/retrieval/config/update` 修正。API response JSON 作为证据存档。

## 4) 执行角色分工

本测试由 Agent（AI）主导执行，尽可能通过 Open WebUI API 自动化，User 仅负责 API 无法覆盖的操作。

| 职责 | Owner | 方式 |
| --- | --- | --- |
| 切换 Embedding 模型 | **Agent** | `POST /api/v1/retrieval/embedding/update` |
| 修改 RAG 参数（chunk/top_k/hybrid） | **Agent** | `POST /api/v1/retrieval/config/update` |
| 重置向量库 | **Agent** | `POST /api/v1/retrieval/reset/db` |
| 读取/验证当前配置 | **Agent** | `GET /api/v1/retrieval/embedding` + `GET /api/v1/retrieval/config` |
| Host 上 docker compose 操作 | **User** | Agent 给出可复制命令，User 执行并回传输出 |
| 上传文档到 Open WebUI | **User** | Agent 给出文件清单和上传顺序，User 在 UI 中操作 |
| 在 Open WebUI 中提问并收集回答 | **User** | Agent 给出完整题目，User 逐条提问并将回答（含来源引用）回传 |
| 记录结果、评分、计算指标、产出结论 | **Agent** | 基于 User 回传内容，Agent 自动填表并判定 |

工作流程: Agent 通过 API 配置环境 -> 指示 User 上传文档 -> 给出题目 -> User 提问并回传 -> Agent 记录评分并推进。

### 测试报告同步更新规则

Agent 在测试执行过程中，必须以 `docs/testing/reports/rag-ab-results-template.md` 为模板，实时同步更新测试报告:

1. **测试开始前**: 以模板为基础在 `docs/testing/reports/` 目录下创建本轮测试报告（如 `rag-ab-results-2026-02-24.md`），填写头部元信息（填写人、日期、版本）。
2. **每轮 Round 开始时**: 将 API 验证结果（Embedding 配置、RAG 参数、向量库重置）记录到报告的「API 证据留存」节。
3. **每条问题回答后**: 立即将 hit@1、hit@5、latency、score、hallucination、notes 填入对应 Round 的记录表，不要等整轮结束后批量填写。
4. **每轮 Round 结束后**: 核算该轮汇总指标（Recall@5、Top1 Hit、Avg Score、P95 Latency）。
5. **全部 4 轮结束后**: 填写门槛核对表和 Go/No-Go Checklist，产出最终结论。

## 5) 偏差控制与异常处理

### 偏差控制

- 每轮（A1/B1/A2/B2）开始前必须由 Agent 调用 `POST /api/v1/retrieval/reset/db` 重置向量库，确认 API 返回成功后再上传文档。
- 每轮提问使用独立的新聊天会话，不复用历史会话。
- A 类和 B 类问题（Q01-Q20）可在同一会话中顺序提问。C 类追问链（Q21-Q28）必须按分组在同一会话中连续提问，追问链断链（如意外切换会话）则整组作废并重跑。
- 提问节奏: 等上一条回答完全生成后再提下一问，不要并发。

### 异常处理

- **技术失败**（超时、500 错误、连接中断）: 允许重试 1 次，在 notes 中记录 `retry:技术原因`。
- **内容异常**（答非所问但系统正常）: 不重试，按真实结果记录。
- **连续技术失败** >= 3 次: 暂停测试，排查环境问题后从当前 Round 重新开始。

## 6) 证据留存

每轮执行需保留以下证据（存放在 `docs/testing/reports/` 目录下）:

- **RAG 参数验证 JSON**（每轮一次）: Agent 调用 `GET /api/v1/retrieval/config` 的完整 response，确认参数一致
- **Embedding 模型验证 JSON**（每轮一次）: Agent 调用 `GET /api/v1/retrieval/embedding` 的完整 response，确认 A 轮用 MiniLM、B 轮用 bge-m3
- **向量库重置确认 JSON**（每轮一次）: Agent 调用 `POST /api/v1/retrieval/reset/db` 的 response
- 填写完成的测试报告（基于模板创建，如 `rag-ab-results-2026-02-24.md`，见第 4 节同步更新规则）
- 可选: 导出聊天记录原文（如 Open WebUI 支持导出）

注意: 所有 API response JSON 由 Agent 在执行过程中自动记录到结果报告中，无需 User 手动截图。

## 7) 执行步骤（按顺序）

按模型分组执行：先跑完 MiniLM（A1 + A2），再跑 bge-m3（B1 + B2）。减少模型切换次数，每轮独立重置向量库，不影响结果。

执行矩阵:

| 顺序 | Run | Embedding | 文档集 |
| --- | --- | --- | --- |
| 1 | A1 | all-MiniLM-L6-v2 | Phase 1 固定书单 |
| 2 | A2 | all-MiniLM-L6-v2 | Phase 1 书单 + D06 + D07（共 7 本） |
| 3 | B1 | bge-m3 | Phase 1 固定书单 |
| 4 | B2 | bge-m3 | Phase 1 书单 + D06 + D07（共 7 本） |

### 本次执行调整（2026-02-24）

由于上游模型 API 在 A1 执行中触发持续限速（`RateLimitError`），A1 仅完成 Q01-Q12。
为保证 A/B 可比性，本轮先采用 **对齐子集比较策略**：

- A1 基线: 使用已完成的 Q01-Q12 结果
- B1 对照: 先完整执行 Q01-Q12（含相同前置烟雾测试）
- Q13-Q28 暂作为补充项，待额度恢复后再补测（不阻塞 B1 开始）

说明：该调整不改变 embedding、chunk、文档、参数等核心对照条件，仅缩小当前可比较样本集。

## 前置烟雾测试（Pre-condition Smoke Test）

在 A1 和 B1 开始正式提问之前，必须先发送一条相同的烟雾测试问题，用于：
1. 验证 RAG 检索链路正常工作（embedding → vector search → LLM）
2. 确保 A/B 两组的会话起点条件一致（相同的第一轮交互）

**烟雾测试问题（固定，不可变更）:**
> What does Clean Code say about meaningful variable names? Give a brief answer.

**执行规则:**
- 该问题不计入正式评分（不影响 Recall@5、Top1 Hit 等指标）
- A1 和 B1 必须使用完全相同的问题文本
- 烟雾测试的回答保存在聊天记录中，但在结果统计时标记为 `[PRE]`
- 如果烟雾测试失败（API 报错或无法检索），则暂停排查，不继续正式测试

## Round A1（Phase 1 基线: MiniLM）

1. **[Agent]** 调用 `GET /api/v1/retrieval/embedding` 确认当前 Embedding 模型为 `all-MiniLM-L6-v2`。若不是，调用 `POST /api/v1/retrieval/embedding/update` 切换（payload 见第 13 节 API Reference）。将 API response JSON 存档。
2. **[Agent]** 调用 `GET /api/v1/retrieval/config` 确认 RAG 参数（chunk_size=900, chunk_overlap=200, top_k=5, hybrid=ON）。若不一致，调用 `POST /api/v1/retrieval/config/update` 修正。将 API response JSON 存档。
3. **[Agent]** 调用 `POST /api/v1/retrieval/reset/db` 重置向量库。将 API response 存档。
4. **[User]** 按 Phase 1 固定书单（D01-D05）在 Open WebUI 中重新上传全部文档，确认上传成功并回传确认。
5. **[Agent]** 新建专用聊天（命名: `RAG-AB-A1`），先发送前置烟雾测试问题（见上节），确认 RAG 正常后继续。
6. **[Agent]** 逐条提问第 10 节 `Phase 1` 问题集（Q01-Q28），通过 API 收集回答和来源引用。
7. **[Agent]** 每条问题记录:
   - 返回的来源（top1-top5 文档名/片段）
   - 是否命中期望证据（见第 9 节）
   - 总响应时间（秒，由 User 报告）
   - 回答评分（1-5，由 Agent 判定）

## Round B1（Phase 1 实验: bge-m3）

1. **[User]** 在 Mac 本机安装并启动 Ollama（Docker 容器内无法使用 Metal GPU，必须在宿主机运行）。

   ```bash
   # 安装（二选一）
   brew install ollama          # Homebrew
   # 或从 https://ollama.com/download 下载 macOS app

   # 启动 Ollama 服务
   ollama serve                 # 如使用 app 版，启动 app 即可

   # 拉取 bge-m3 并验证
   ollama pull bge-m3
   ollama list                  # 确认 bge-m3:latest 存在
   ```

   验证 GPU 加速生效:
   ```bash
   # 应输出 Metal GPU 信息，而非 "100% CPU"
   ollama ps
   ```

   > **注意**: 如之前在 Docker 中运行过 Ollama 容器，需先停止:
   > `docker stop ollama` 或确保 docker-compose.yml 中 ollama 服务已加 `profiles: [ollama-docker]`。
   > 端口 11434 不能被两个 Ollama 实例同时占用。

2. **[User]** 验证 Open WebUI 容器可访问宿主机 Ollama:

   ```bash
   docker exec open-webui curl -s http://host.docker.internal:11434/api/tags
   ```
   应返回包含 `bge-m3:latest` 的 JSON。

3. **[Agent]** 调用 `POST /api/v1/retrieval/embedding/update` 切换到 bge-m3，`ollama_config.url` 指向宿主机（payload 见第 13 节 API Reference）。将 API response JSON 存档。
4. **[Agent]** 调用 `GET /api/v1/retrieval/embedding` 验证切换成功：确认 `RAG_EMBEDDING_ENGINE=ollama`、`RAG_EMBEDDING_MODEL=bge-m3:latest`、`ollama_config.url=http://host.docker.internal:11434`。将 API response JSON 存档。
5. **[Agent]** 调用 `GET /api/v1/retrieval/config` 验证 RAG 参数与 A1 一致（chunk_size=900, chunk_overlap=200, top_k=5, hybrid=ON）。若不一致，先调用 `POST /api/v1/retrieval/config/update` 修正后再继续。将 API response JSON 存档。
6. **[Agent]** 调用 `POST /api/v1/retrieval/reset/db` 重置向量库。将 API response 存档。
7. **[User]** 用与 A1 完全相同的 Phase 1 书单（D01-D05）在 Open WebUI 中重新上传。
8. **[Agent]** 新建聊天（命名: `RAG-AB-B1`），先发送前置烟雾测试问题（见「前置烟雾测试」节），确认 RAG 正常后继续。
9. **[Agent]** 用同一题集 Q01-Q28、同一顺序提问，通过 API 收集回答和来源引用。
10. **[Agent]** 用与 A1 完全相同的记录方式填写结果。

## Round A2（Phase 2 泛化评测: MiniLM）

1. **[Agent]** 调用 `POST /api/v1/retrieval/embedding/update` 切换回 MiniLM（payload 见第 13 节 API Reference）。将 API response JSON 存档。
2. **[Agent]** 调用 `GET /api/v1/retrieval/embedding` 验证切换成功：确认 `RAG_EMBEDDING_ENGINE=""`、`RAG_EMBEDDING_MODEL=all-MiniLM-L6-v2`。将 API response JSON 存档。
3. **[Agent]** 调用 `GET /api/v1/retrieval/config` 验证 RAG 参数与第 3.2 节固定值一致（chunk_size=900, chunk_overlap=200, top_k=5, hybrid=ON）。若不一致，先调用 `POST /api/v1/retrieval/config/update` 修正后再继续。将 API response JSON 存档。
4. **[Agent]** 调用 `POST /api/v1/retrieval/reset/db` 重置向量库。将 API response 存档。
5. **[User]** 上传全部 7 本文档（D01-D07），即 Phase 1 的 5 本 + IPv6 + 我的奋斗，确认上传成功并回传确认。
6. **[User]** 新建聊天（命名: `RAG-AB-A2`）。
7. **[User]** 逐条提问第 10 节 `Phase 2` 问题集（Q29-Q40），将每条回答（含来源引用）回传给 Agent。
8. **[Agent]** 用与 A1 完全相同的记录方式填写结果。

## Round B2（Phase 2 泛化评测: bge-m3）

1. **[Agent]** 调用 `POST /api/v1/retrieval/embedding/update` 切换回 bge-m3（payload 见第 13 节 API Reference）。将 API response JSON 存档。
2. **[Agent]** 调用 `GET /api/v1/retrieval/embedding` 验证切换成功：确认 `RAG_EMBEDDING_ENGINE=ollama`、`RAG_EMBEDDING_MODEL=bge-m3:latest`。将 API response JSON 存档。
3. **[Agent]** 调用 `GET /api/v1/retrieval/config` 验证 RAG 参数与 A2 一致（chunk_size=900, chunk_overlap=200, top_k=5, hybrid=ON）。若不一致，先调用 `POST /api/v1/retrieval/config/update` 修正后再继续。将 API response JSON 存档。
4. **[Agent]** 调用 `POST /api/v1/retrieval/reset/db` 重置向量库。将 API response 存档。
5. **[User]** 上传全部 7 本文档（D01-D07），与 A2 相同，确认上传成功并回传确认。
6. **[User]** 新建聊天（命名: `RAG-AB-B2`）。
7. **[User]** 逐条提问 Q29-Q40，同一顺序，将每条回答（含来源引用）回传。
8. **[Agent]** 用与 B1 完全相同的记录方式填写结果。

注意: Phase 2 结果单独统计，不与 Phase 1 混算。

## 8) 记录模板（放同一份表里）

建议建一个 `rag_ab_results.csv`，字段如下:

```csv
run,query_id,query,expected_doc_or_keyword,retrieved_top1,retrieved_top3,retrieved_top5,hit_at_1,hit_at_5,latency_sec,answer_score_1_5,hallucination_yn,notes
A1,Q01,"《A Philosophy of Software Design》里 deep module 的核心含义是什么？","deep module",,,,
B1,Q01,"《A Philosophy of Software Design》里 deep module 的核心含义是什么？","deep module",,,,
```

字段说明:

- `run`: A1 / B1 / A2 / B2
- `expected_doc_or_keyword`: 期望命中的证据（文档名、章节名、关键词）
- `hit_at_1`: top1 是否命中（0/1）
- `hit_at_5`: top5 是否命中（0/1）
- `answer_score_1_5`: 人工评分
- `hallucination_yn`: 是否出现明显编造（Y/N）

## 9) 判定规则（实操版）

因为 Open WebUI UI 不一定直接展示 chunk_id，这里用"证据命中"代替 chunk_id 命中。

判定命中规则:

- 如果检索来源中出现 `expected_doc_or_keyword`，记为命中。
- 若 top1 命中，`hit_at_1=1`。
- 若 top1 未命中但 top5 内有命中，`hit_at_5=1`。
- 若 top5 都没命中，`hit_at_1=0` 且 `hit_at_5=0`。

回答评分规则（1-5）:

- 5: 正确、完整、紧扣资料、无幻觉
- 4: 基本正确，有轻微遗漏
- 3: 部分正确，缺关键点
- 2: 明显偏题或证据不足
- 1: 错误/编造

## 10) 具体问题集（Q01-Q40）

说明:

- Q01-Q28: Phase 1 固定书单（主评测）
- Q29-Q40: Phase 2 多样化书单（泛化评测）
- 若某题与实际文档轻微不匹配，可替换同类问题，但保留题号。

### A类（Phase 1）: 中问英答（Q01-Q10）

- Q01: 《A Philosophy of Software Design》里 deep module 的核心含义是什么？
- Q02: 《A Philosophy of Software Design》如何解释 complexity 的来源？
- Q03: 《The Pragmatic Programmer》中的 DRY 原则在实务上怎么落地？
- Q04: 《The Pragmatic Programmer》里的 tracer bullet 和 prototype 有什么区别？
- Q05: 《Tidy First》里 "先整理再改功能" 的核心理由是什么？
- Q06: 《TDD by Example》中的 red-green-refactor 三步法具体怎么执行？
- Q07: 《Pro Git》里 working tree、staging area、repository 三者关系是什么？
- Q08: 《Pro Git》建议什么时候使用 rebase，什么时候用 merge？
- Q09: 《Pro Git》里 `git fetch` 和 `git pull` 的区别是什么？
- Q10: 《The Pragmatic Programmer》里 Broken Windows 理念在代码维护中怎么应用？

### B类（Phase 1）: 英问英答（Q11-Q20）

- Q11: In APOSD, what is the practical definition of a deep module?
- Q12: In APOSD, how does the book distinguish tactical programming vs strategic programming?
- Q13: In The Pragmatic Programmer, what is "orthogonality" in system design?
- Q14: In The Pragmatic Programmer, why is "automation" emphasized for engineering quality?
- Q15: In Tidy First, what is the difference between behavior change and structure change?
- Q16: In TDD by Example, how are tests used to drive design decisions?
- Q17: In Pro Git, what does `git reset --soft` change compared with `--mixed`?
- Q18: In Pro Git, when should `git cherry-pick` be preferred?
- Q19: In Pro Git, what does `HEAD` represent and why does it matter?
- Q20: In Tidy First, why are small reversible changes preferred?

### C类（Phase 1）: 追问与省略上下文（Q21-Q28）

追问链规则: 每组必须在同一聊天会话中按顺序连续提问。如果中途断链（意外切换会话、刷新丢失上下文），则该组全部作废并重跑。

- Q21: （先问）解释一下 APOSD 的 deep module。
- Q22: （紧接 Q21）给一个在实际代码里的例子。
- Q23: （紧接 Q22）那 shallow module 在这里对应什么反例？
- Q24: （先问）总结一下 TDD by Example 的核心流程。
- Q25: （紧接 Q24）那这个流程在重构旧代码时怎么用？
- Q26: （先问）Pro Git 里讲的三棵树模型再解释一下。
- Q27: （紧接 Q26）那我刚才这个场景应该用哪种 reset？
- Q28: （先问）如果 TDD 中测试很难下手，应该如何拆小需求？

### D类（Phase 2）: 多样化与关键词精确匹配（Q29-Q40）

说明: Phase 2 问题分三组——
- Q29-Q34: 复测 Phase 1 书籍（验证新增 D06/D07 不干扰原有检索质量）
- Q35-Q38: 测试新增文档 D06（IPv6）和 D07（我的奋斗）
- Q39-Q40: 跨书综合问题（测试多文档语义关联能力）

- Q29: `git rebase --onto` use case
- Q30: `git reset --hard` vs `git checkout -- <file>` difference
- Q31: `git reflog` recover lost commit
- Q32: `red-green-refactor` strict definition
- Q33: `deep module` vs `information hiding`
- Q34: `behavior change` vs `structure change` in Tidy First
- Q35: `IPv6 link-local address` prefix and usage
- Q36: `IPv6 SLAAC` workflow keywords
- Q37: 《我的奋斗》里作者关于创业风险的原话或观点
- Q38: 《我的奋斗》里一次失败经历及其复盘
- Q39: 跨书问题：TDD 和 Tidy First 在“先做什么”上有什么张力？
- Q40: 跨书问题：APOSD 的复杂度观点如何解释 Pragmatic Programmer 的工程建议？

## 11) 结果计算（手工或表格都可）

最少计算以下 8 个数字:

- A1_Recall@5 / B1_Recall@5（Phase 1）
- A1_Top1 / B1_Top1（Phase 1）
- A1_AvgScore / B1_AvgScore（Phase 1）
- A1_P95 / B1_P95（Phase 1）
- A2_Recall@5 / B2_Recall@5（Phase 2）
- A2_Top1 / B2_Top1（Phase 2）
- A2_AvgScore / B2_AvgScore（Phase 2）
- A2_P95 / B2_P95（Phase 2）

可直接写在结论表:

| 指标 | A | B | 变化 | 是否达标 |
| --- | --- | --- | --- | --- |
| Phase1 Recall@5 |  |  |  |  |
| Phase1 Top1 Hit |  |  |  |  |
| Phase1 Avg Score |  |  |  |  |
| Phase1 P95 Latency |  |  |  |  |
| Phase2 Recall@5 |  |  |  |  |
| Phase2 Top1 Hit |  |  |  |  |
| Phase2 Avg Score |  |  |  |  |
| Phase2 P95 Latency |  |  |  |  |

## 12) 最终结论模板

```md
结论: Go / No-Go

原因:
1. Phase1 Recall@5: xx% -> xx%（+xx%）
2. Phase1 Top1: xx% -> xx%（+xx%）
3. Phase1 回答均分: x.x -> x.x
4. Phase1 P95延迟: x.xs -> x.xs
5. Phase2 是否出现明显退化: Yes/No

上线决策:
- 若 Go: 切换 bge-m3，保留 smoke 回归集:
  - Q01（中问英答/APOSD）、Q07（中问英答/Git）
  - Q12（英问英答/APOSD）、Q21（追问链/APOSD）
  - Q25（追问链/TDD重构）、Q31（关键词/reflog）
  - Q35（IPv6新文档）、Q39（跨书综合）
- 若 No-Go: 回滚 MiniLM，记录失败样本并迭代 query template 或 chunk 参数后重测。
```

## 13) API Reference（Agent 执行用）

本节列出 Agent 在测试执行中使用的全部 Open WebUI API 端点。

**通用信息:**
- Base URL: `http://localhost:3000`（宿主机）/ `http://open-webui:8080`（Docker 内部）
- 认证: `Authorization: Bearer sk-3d600f3d6d614350a476560a6e31e1c7`
- 所有请求和响应均为 JSON

### 13.1 获取当前 Embedding 配置

```
GET /api/v1/retrieval/embedding
Authorization: Bearer <API_KEY>
```

预期响应示例:
```json
{
  "status": true,
  "RAG_EMBEDDING_ENGINE": "",
  "RAG_EMBEDDING_MODEL": "all-MiniLM-L6-v2"
}
```

### 13.2 切换 Embedding 模型

**切换到 bge-m3:**
```
POST /api/v1/retrieval/embedding/update
Authorization: Bearer <API_KEY>
Content-Type: application/json

{
  "RAG_EMBEDDING_ENGINE": "ollama",
  "RAG_EMBEDDING_MODEL": "bge-m3:latest",
  "ollama_config": {"url": "http://host.docker.internal:11434", "key": ""}
}
```

> 注: `host.docker.internal` 用于从 Open WebUI 容器内访问 Mac 宿主机上运行的 Ollama。
> 如在 Linux + Docker Ollama 容器场景，改回 `http://ollama:11434`。

**切换回 MiniLM:**
```
POST /api/v1/retrieval/embedding/update
Authorization: Bearer <API_KEY>
Content-Type: application/json

{
  "RAG_EMBEDDING_ENGINE": "",
  "RAG_EMBEDDING_MODEL": "all-MiniLM-L6-v2"
}
```

### 13.3 获取 RAG 配置

```
GET /api/v1/retrieval/config
Authorization: Bearer <API_KEY>
```

用于验证 chunk_size、chunk_overlap、top_k、hybrid search 等参数。

### 13.4 更新 RAG 配置

```
POST /api/v1/retrieval/config/update
Authorization: Bearer <API_KEY>
Content-Type: application/json

{
  "chunk": {"chunk_size": 900, "chunk_overlap": 200},
  "top_k": 5,
  "hybrid_search": true
}
```

注意: payload 字段名以实际 API 返回为准，Agent 首次执行时应先 GET 确认字段结构。

### 13.5 重置向量库

```
POST /api/v1/retrieval/reset/db
Authorization: Bearer <API_KEY>
```

预期响应:
```json
{
  "status": true,
  "message": "Vector database reset successfully"
}
```

### 13.6 列出知识库

```
GET /api/v1/knowledge/
Authorization: Bearer <API_KEY>
```

用于验证文档上传后知识库状态。
