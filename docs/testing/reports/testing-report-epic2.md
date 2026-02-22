# Epic 2 人工验证测试报告（Open WebUI）

日期: 2026-02-21
测试依据: `docs/testing/plans/testing-plan-epic2.md` v2.0
测试环境: macOS + Docker + devcontainer/VS Code Port Forward
模型: openai/claude-sonnet-4-6（via claude-max-proxy, subscription profile）

## 1. 测试目标与范围

- 目标: 验证 Epic 2 核心链路可用（RAG 检索 → 学习计划生成 → 概念关系抽取 → 数据落库一致性）。
- 范围: 按 `docs/testing/plans/testing-plan-epic2.md` 的 Step 1-11 执行，记录故障、排查、修复与结论。

## 2. 结果总览

| 步骤 | 结果 | 备注 |
|---|---|---|
| Step 1 RAG 基础检索 | **部分通过**（R5 Buffer+Discard 确认），OAuth 阻塞 | R1-4: double-response 迭代修复；R5: Buffer 机制通过，OAuth 过期阻塞完整验证 → Issue #10 |
| Step 2 RAG 连续追问 | 未测 | Step 1 阻塞 |
| Step 3 学习计划生成 | 未测 | |
| Step 4 学习计划可追问性 | 未测 | |
| Step 5 关系抽取 | 未测 | |
| Step 5.5 关系抽取幂等性 | 未测 | |
| Step 6 关系可用性验证 | 未测 | |
| Step 7 Fail Soft | 未测 | |
| Step 8 Epic 2 相关测试集 | 未测 | |
| Step 9 全量回归 | 未测 | |
| Step 10 数据落库抽检 | 未测 | |
| Step 11 计划与关系数据抽检 | 未测 | |

## 3. 分步骤测试与排障记录

### Step 1: RAG 基础检索

---

#### Round 1（失败 — double-response bug）

- 测试输入: `请基于我上传的资料，解释"幂等性"，并给出来源依据。`
- 上传文档: 1 份 PDF（Python Crash Course, 3rd Edition）

- 问题排查路径:

  - **阶段 A：工具调用成功，检索结果正确**
    - Agent 自动调用 `list_knowledge_bases`，返回:
      ```json
      {
        "knowledge_bases": [{
          "name": "default",
          "display_name": "Default Knowledge Base",
          "document_count": 4,
          "documents": [
            "凤凰架构：构建可靠的大型分布式系统.pdf",
            "System Design Interview – An insider's guide by Alex Xu (z-lib.org).pdf",
            "深入理解Java虚拟机：JVM高级特性与最佳实践（第3版）.pdf",
            "Designing Data-Intensive Applications.pdf"
          ]
        }]
      }
      ```
    - Agent 调用 `search_knowledge_base`，返回 10 条结果（score 0.62~0.68），主要来自《凤凰架构》和《DDIA》。
    - 结论: RAG 工具链路正常，检索结果相关且有来源标注。
    - 附带发现: 用户只上传了 1 份 PDF，但 default knowledge base 显示 4 份文档（见 Issue #2）。

  - **阶段 B：第一段回答生成（正确）**
    - Agent 基于 10 条检索结果生成了完整的幂等性解释：
      - 引用《凤凰架构》的定义、重要性、设计方案
      - 引用《DDIA》的分布式系统幂等性必要性
      - 包含 CRUD 幂等性分析表格、幂等 Token 方案、支付场景举例
    - 结论: 回答质量高，满足 Step 1 通过标准（基于资料、有来源痕迹、结构化）。

  - **阶段 C：异常的第二轮工具调用（double-response bug）**
    - 第一段回答结束后，界面继续出现:
      ```text
      💭 Thinking...
      🔧 Running list_knowledge_bases...
      🔧 Running search_knowledge_base...
      ```
    - 第二轮工具调用**失败**（API 认证错误/参数错误）。
    - Agent 生成**第二段回答**:
      > "我注意到你的消息中包含了一些工具调用的错误信息……🔴 本次工具调用失败——知识库搜索工具遇到了 API 认证错误和参数错误，没有成功检索你上传的资料。"
    - 结论: 第二段回答与第一段矛盾（第一段说有来源，第二段说工具失败），用户感知为"agent 无法访问文档"。
    - 根因: 见 Issue #1 详细分析。

  - **阶段 D：修复 double-response bug**
    - 根因定位后，在 `agent_service.py` 的 `_agent_loop` 中增加 `content_forwarded` guard：
      ```python
      if finish_reason == "tool_calls" and getattr(choice.message, "tool_calls", None):
          if content_forwarded:
              logger.warning(
                  "tool-loop(stream) content already forwarded but LLM "
                  "requested more tool_calls — breaking to prevent "
                  "double response (iteration=%s)", iteration + 1,
              )
              break
          # ... 正常工具执行路径不变 ...
      ```
    - 新增 2 个单元测试:
      - `test_double_response_guard_breaks_when_content_forwarded`: 模拟 LLM 同时返回 content + tool_calls，验证 loop break、不执行工具、SSE 正常终结
      - `test_normal_tool_loop_unaffected_by_guard`: 验证正常 tool loop（无 content 的工具迭代 → 有 content 的最终回答）不受 guard 影响
    - 回归结果: `pytest tests/ -q` → **237 passed**（235 原有 + 2 新增）
    - 结论: 修复已合入，待重启容器后复测 Step 1。

  - **阶段 E：补充定位 API Key 权限问题**
    - 复测链路时，从 `agent-service` 容器直连 Open WebUI Knowledge API：
      - `GET /api/v1/knowledge/` 返回 `401 Unauthorized`（旧 `OPENWEBUI_API_KEY=dev-key` 无效/无权限）。
    - 更换为 Open WebUI 新生成的 API Key 后复测：
      - `GET /api/v1/knowledge/` 返回 `200`；
      - 已能看到用户实际使用的 `Python` collection（不再只看到 default）。
    - 结论：第二段回答中的"工具认证失败"与 API Key 配置错误直接相关。

  - **阶段 F：补充定位 Open WebUI 容器重启原因**
    - 在重新上传 PDF 后，观察到 `open-webui` 容器重启。
    - 通过 `docker events` 确认：发生 `container oom`，随后 `exitCode=137` 并自动重启。
    - 结论：该重启为内存不足导致（OOM），不是手动重启或应用正常重启。

- 判定（Round 1）: **失败**。

---

#### Round 2（失败 — guard 副作用 + 中英文 embedding 不匹配）

- 修复清单: Issue #1 guard 代码、Issue #2 API Key
- 容器重建: `docker compose build --no-cache agent-service`

- **复测 2a: 查询"幂等性"**
  - 测试输入: `请基于我上传的资料，解释"幂等性"，并给出来源依据。`
  - 结果: agent 生成了两段回答，第一段包含伪造的 Fluent Python 引用（`[Tool Result: search_knowledge_base - call_56c2e0b8]` 等文本块），第二段承认伪造。
  - 排查:
    - 初次 `--build` 未使用 `--no-cache`，容器仍运行旧代码（grep 确认 guard 不在镜像中）。
    - 使用 `--no-cache` 重建后，grep 确认 guard 代码（line 199）已进入容器。
    - `curl` 直测 retrieval API：KB ID `567266f8-...` 作为 `collection_names` 有效，API 返回 200。
    - 搜索结果（query="幂等性"）返回 Python 循环代码片段（score 0.60~0.63），与幂等性无关。
  - 根因: embedding 模型 `all-MiniLM-L6-v2` 为英语优化，中文查询 "幂等性" 无法匹配英文书籍内容。
  - 修复: `search_knowledge_base` tool schema 的 `query` 参数描述中增加: `"IMPORTANT: Always formulate queries in English"`。

- **复测 2b: 查询"列表推导式"（guard 部署后首次测试）**
  - 测试输入: `请基于我上传的资料，解释 Python 中的列表推导式（list comprehension），并给出来源依据。`
  - 结果: Agent 生成了完整回答（苏格拉底式提问 + 通用知识解释），但**未引用上传资料**。声称 "如果工具未返回相关段落，我会明确告知"。
  - 排查:
    - agent-service 日志确认:
      ```
      tool-loop(stream) content already forwarded but LLM requested more tool_calls — breaking to prevent double response (iteration=1)
      ```
    - **Guard 在 iteration 1 就触发了** — LLM 在流式输出回答文本的同时请求了 tool_calls，guard 阻止了工具执行。`search_knowledge_base` **从未被调用**。
    - `curl` 直测 `"list comprehension"` 查询: API 返回 200，score 0.77+，命中 Python Crash Course Chapter 3 内容。
  - 根因: LLM 行为模式不对 — 在同一 response 中同时输出文本 + 请求工具。Guard 正确拦截了 double-response，但副作用是工具不执行。
  - 修复: `mentor_system_prompt.md` 新增 `## Tool Usage Protocol`（4 条规则），告知 LLM 先调工具、再输出文本，不要在同一 response 中混合。

- 判定（Round 2）: **失败**（工具未执行，无 RAG 来源）。

---

#### Round 3（失败 — Guard 过于激进 + system prompt 软约束无效）

- 修复清单（Round 2 → 3 之间）:
  1. `agent_service.py:199` — content_forwarded guard（Issue #1）
  2. `.env` — OPENWEBUI_API_KEY 更新（Issue #2）
  3. `__init__.py` — search query 英文指令（Issue #4）
  4. `mentor_system_prompt.md` — Tool Usage Protocol（Issue #5）
- 容器重建: `docker compose build --no-cache agent-service`

- **测试**:
  - 测试输入: `请基于我上传的资料，解释 Python 中的列表推导式（list comprehension），并给出来源依据。`
  - 结果: Agent 回答 "Knowledge Bases found. Let me search for list comprehension content in your materials." 后声称 "未能找到与'列表推导式'直接相关的资料片段"，给出通用知识回答（无 RAG 来源引用）。
  - 排查:
    - agent-service 日志确认 Guard **再次在 iteration 1 触发**:
      ```
      tool-loop(stream) content already forwarded but LLM requested more tool_calls — breaking to prevent double response (iteration=1)
      ```
    - System prompt 的 Tool Usage Protocol **未被 LLM 遵守** — LLM 仍然在同一 response 中混合文本 + tool_calls。
    - 英文查询指令已确认在容器中（`grep -n "English"` 命中 line 47-48）。
  - 根因: Issue #5 的 system prompt 修复是软约束，LLM 不遵守时无 fallback。而 Issue #1 的 Guard 在 `iteration == 0` 就 break，导致工具完全不执行（比 double-response 更严重）。
  - 修复: 见 Issue #7 — 改进 Guard 逻辑，区分首次工具调用与后续迭代。

- 判定（Round 3）: **失败**（Guard 阻止首次工具执行，无 RAG 来源）。

---

#### Round 4（失败 — `content_forwarded` 按迭代重置，跨迭代追踪缺失）

- 修复清单（Round 3 → 4 之间）:
  1. Issue #7: Guard v2 — `iteration == 0` 时允许工具执行
- 容器重建: `docker compose build --no-cache agent-service`（确认 `iteration > 0` 在容器 line 198）

- **测试**:
  - 测试输入: `请基于我上传的资料，解释 Python 中的列表推导式（list comprehension），并给出来源依据。`
  - 结果: Agent 先输出完整回答（无 RAG 引用），然后继续调用 `list_knowledge_bases` + `search_knowledge_base`（多次 422 失败），最终生成第二段回答。Double-response 再次出现。
  - 排查:
    - Guard v2 在 iteration 0 正确放行了工具执行（符合预期）
    - 但 `content_forwarded` 在每次 iteration 开头被重置为 `False`（line 170）
    - Iteration 1 时 LLM 只返回 tool_calls（无 content）→ `content_forwarded=False` → Guard 不触发
    - 后续迭代持续执行工具（均 422 失败），最终 LLM 生成第二段回答
  - 根因: Guard 只检查**当前迭代**的 `content_forwarded`，缺少跨迭代追踪。见 Issue #8。
  - 修复: Guard v3 — 新增 `any_content_ever_forwarded` 跨迭代标志。

- 判定（Round 4）: **失败**（double-response 再现）。

---

#### Round 5（部分通过 — Buffer + Discard 确认工作，OAuth 阻塞）

- 修复清单（Round 4 → 5 之间）:
  1. Issue #8: Guard v3 — `any_content_ever_forwarded` 跨迭代追踪（已实现但发现设计缺陷）
  2. Issue #9: **废弃整个 Guard 方案，改用 Buffer + Discard**（最终方案）
  3. 单元测试：4 个 Guard 测试替换为 3 个 Buffer 测试，全量 238 passed
- 容器重建: `docker compose build --no-cache agent-service && docker compose up -d agent-service`

- **测试**:
  - 测试输入: `请基于我上传的资料，解释 Python 中的列表推导式（list comprehension），并给出来源依据。`
  - **Buffer + Discard 行为确认（通过）**:
    - SSE 事件顺序正确：`status("💭 Thinking...")` → `status("🔧 Running list_knowledge_bases...")` → `status("🔧 Running search_knowledge_base...")` → content chunks
    - Status 事件出现在 content **之前**（与旧方案相反），证明 buffer 机制生效：content 被缓冲到最终 `stop` 才 flush
    - **无 double-response** — 只出现一段回答
    - 工具跨多次迭代正常执行，未被阻断
  - **search_knowledge_base 返回 422（失败）**:
    - `list_knowledge_bases` 成功执行（返回知识库列表）
    - `search_knowledge_base` 两次调用均返回 HTTP 422 Unprocessable Entity
    - 改进了 `_handle_openwebui_error` 错误处理（新增 response body 输出用于诊断）
    - 直接 curl 测试 Open WebUI retrieval API（UUID 作为 collection_names）→ 200 OK，4 条结果（score 0.77+）
    - 初步假设：LLM 传递 `collection_names` 参数格式不正确（string vs array），未最终确认
  - **OAuth token 过期（阻塞后续测试）**:
    - 测试中发现 claude-max-proxy 返回 401: `"OAuth token has expired"`
    - 触发 Issue #10 排查

- 判定（Round 5）: **部分通过**（Buffer + Discard 核心机制确认，422 和 OAuth 阻塞完整验证）。

---

#### Round 6（待测 — OAuth 修复后）

- 修复清单（Round 5 → 6 之间）:
  1. Issue #10: proxy 认证架构改造（独立 OAuth 流程，不再依赖静态 token 导出）
  2. 改进 `search_knowledge_base_tool.py` 的 422 错误处理（含 response body 诊断）
- 待执行: proxy OAuth 改造完成后重建容器并复测 Step 1

## 4. Issue 列表

### Issue #1: Streaming Agent Loop Double-Response Bug

**严重程度**: HIGH（阻塞所有用户侧验收步骤）
**发现步骤**: Step 1 Round 1
**修复状态**: 已修复（v1 → v2 → v3 迭代，见 Issue #7 / #8）

**现象**: 用户发送一条消息，agent 产生两轮回答。第一段正确（有 RAG 来源引用），第二段错误（声称工具调用失败）。

**根因分析**:

`agent_service.py` 的 `_agent_loop()`:

1. **Iteration 1**: LLM → `finish_reason="tool_calls"` → 工具成功 → results 追加到 messages
2. **Iteration 2**: LLM 收到 results → 生成完整文本（`content_forwarded = True`）**+** 同时请求 `tool_calls` → loop 未检查 `content_forwarded` → 继续执行工具（失败）
3. **Iteration 3**: LLM 看到失败 → 生成第二段矛盾回答

**修复 v1**（Round 2）: `agent_service.py:199` 增加 `content_forwarded` guard — 当 content 已流给用户时，break loop。
- 副作用：Guard 过于激进，在 iteration 0 就 break，导致工具完全不执行（Round 2/3 失败）。

**修复 v2**（Round 4，Issue #7）: Guard 增加 `iteration > 0` 条件 — 仅在工具已执行过之后才 break，首次工具调用允许执行。
- 副作用：`content_forwarded` 按迭代重置，iteration 1+ 检测不到之前已有 content（Round 4 失败）。

**修复 v3**（Issue #8）: 新增 `any_content_ever_forwarded` 跨迭代标志，解决按迭代重置的漏洞。
- 缺陷：阻断合法多步工具链（iteration 0 有 content → iteration 1 只有 tool_calls → Guard break → 搜索工具不执行）。

**修复 v4（最终）**（Issue #9）: **废弃整个 Guard 方案，改用 Buffer + Discard**。
- 每迭代缓冲 content chunks（不立即流给客户端）
- `finish_reason=="tool_calls"` → 丢弃缓冲，执行工具，继续迭代
- `finish_reason=="stop"` → flush 缓冲到客户端
- 正确性：工具永远能执行，content 永远不会 double-response（因为只在最终 stop 时 flush）
- Codex 架构评审确认此为正确方案

**关联文件**: `agent_service.py:146-240`，`tests/unit/test_agent_service.py`（3 个 buffer 测试替换 4 个 guard 测试），238 全量回归通过。

---

### Issue #2: Open WebUI API Key 无效导致 knowledge base 不可见

**严重程度**: MEDIUM
**发现步骤**: Step 1 Round 1
**修复状态**: 已修复

**现象**: `list_knowledge_bases` 返回 default knowledge base（4 份文档），而非用户实际上传的 `Python` collection。

**根因**: `.env` 中 `OPENWEBUI_API_KEY=dev-key` 无效 → `/api/v1/knowledge/` 返回 401。

**修复**: 更新 `OPENWEBUI_API_KEY` 为 Open WebUI 生成的有效 key。容器内验证 200 OK。

---

### Issue #3: Open WebUI 在重新上传 PDF 后发生 OOM 重启

**严重程度**: MEDIUM（影响测试稳定性）
**发现步骤**: Step 1 Round 1
**修复状态**: 已修复（环境侧）

**现象**: 重新上传 PDF 后，`docker events` 显示 `container oom`，exitCode=137。

**修复动作**: Docker 可用内存已提升至 12GB，并继续采用“上传后等待索引完成”的测试节奏。

**复测结论**: 提升内存后未再出现同类 OOM 重启，问题解除。

---

### Issue #4: 中文查询无法匹配英文文档（embedding 跨语言能力不足）

**严重程度**: MEDIUM
**发现步骤**: Step 1 Round 2
**修复状态**: 已修复（短期方案）

**现象**: 用户用中文查询 "幂等性"，embedding 模型 `all-MiniLM-L6-v2`（英语优化）无法匹配英文文档内容，返回不相关结果（score 0.60~0.63）。

**验证**: `curl` 用英文 `"list comprehension"` 查询同一 collection → score 0.77+，命中 Python Crash Course Chapter 3。

**修复（短期）**: `search_knowledge_base` tool schema 的 `query` 参数增加 `"Always formulate queries in English"` 指令，让 LLM 翻译查询再搜索。

**后续建议（长期）**: 更换多语言 embedding 模型（如 `BAAI/bge-m3`），需重新索引所有文档。

---

### Issue #5: LLM 在同一 response 中混合文本输出与工具调用

**严重程度**: HIGH（与 Issue #1 的 guard 联动，导致工具不执行）
**发现步骤**: Step 1 Round 2
**修复状态**: 软约束（system prompt）+ 硬约束（Issue #7 Guard v2）

**现象**: LLM 在 iteration 1 就同时流式输出回答文本 + 请求 tool_calls。Guard v1 正确拦截了 tool_calls（防 double-response），但副作用是 `search_knowledge_base` 从未执行。

**日志证据**:
```
tool-loop(stream) content already forwarded but LLM requested more tool_calls — breaking to prevent double response (iteration=1)
```

**根因**: LLM 不了解 streaming agent loop 的工具调用协议 — 应先调工具（不输出文本），收到结果后再生成回答。

**修复（软约束）**: `mentor_system_prompt.md` 新增 `## Tool Usage Protocol`:
- 需要工具时，先调用，不生成文本
- 系统自动显示进度指示，不需要 "让我搜索一下"
- 收到工具结果后再生成回答
- **不要在同一 response 中混合文本和工具调用**

**Round 3 验证结论**: System prompt 为软约束，LLM 不一定遵守。需要代码层面硬约束兜底 → Issue #7。

---

### Issue #6: LLM 伪造 Tool Result 文本和引用来源

**严重程度**: MEDIUM
**发现步骤**: Step 1 Round 2（复测 2a）
**修复状态**: 部分修复（system prompt 已有禁伪造指令；Issue #5 修复后不再触发此场景）

**现象**: LLM 在回答中生成了伪造的 `[Tool Result: search_knowledge_base - call_56c2e0b8]` 文本块，包含虚构的 Fluent Python 页码和引用内容。随后在第二段回答中自行承认伪造。

**分析**:
- `mentor_system_prompt.md` 已有明确禁令（line 31-32）: "Never fabricate sources" / "Never fabricate tool call results"
- 该行为在 double-response 场景中出现，LLM 收到不相关的搜索结果后选择编造更合理的引用
- Issue #1 guard + Issue #5 prompt 修复后，double-response 不再发生，此伪造场景不再被触发

---

### Issue #7: Guard 过于激进 — iteration 0 阻止首次工具执行

**严重程度**: HIGH（阻塞 Step 1）
**发现步骤**: Step 1 Round 3
**修复状态**: 已修复

**现象**: Round 3 复测中，LLM 仍然在 iteration 0 混合文本 + tool_calls（Issue #5 system prompt 未被遵守）。Guard v1 在 `iteration == 0` 就 break，导致 `search_knowledge_base` 从未执行，用户无法获得 RAG 来源引用。

**日志证据**（与 Round 2 相同）:
```
tool-loop(stream) content already forwarded but LLM requested more tool_calls — breaking to prevent double response (iteration=1)
```

**根因分析**:
- Guard v1 逻辑: `if content_forwarded: break` — 不区分 iteration 阶段
- `iteration == 0` 时工具还没执行过，break 导致的"无工具执行"比 double-response 更严重
- `iteration >= 1` 时工具已执行过，LLM 有了结果但还要调更多工具 → 才需要 break

**修复**（Guard v2）: `agent_service.py:195-213`，将原有 guard 拆分为两个分支:
```python
if content_forwarded and iteration > 0:
    # 工具已执行过 + content 已流 → break 防 double-response
    break
if content_forwarded:
    # 首次工具调用但 LLM 混合了文本 → 容忍，继续执行工具
    logger.warning("... executing tools anyway ...")
```

**测试**:
- 新增 `test_content_with_first_tool_calls_still_executes_tools`: 验证 iteration 0 时 content + tool_calls → 工具仍执行
- 重写 `test_double_response_guard_breaks_after_tools_executed`: 验证 iteration 1+ 时 content + tool_calls → break
- 保留 `test_normal_tool_loop_unaffected_by_guard`: 正常流程不受影响
- 回归: `pytest tests/ -q` → **238 passed**

---

### Issue #8: Guard `content_forwarded` 按迭代重置，无法跨迭代追踪

**严重程度**: HIGH（阻塞 Step 1）
**发现步骤**: Step 1 Round 4
**修复状态**: 已修复

**现象**: Round 4 中 Guard v2 在 iteration 0 正确放行工具。但 iteration 1+ 时 `content_forwarded` 已被重置为 `False`（每迭代重新初始化），Guard 条件 `content_forwarded and iteration > 0` 不满足，工具继续执行（422 失败），最终 LLM 生成第二段回答。

**根因分析**:
```python
while iteration < max_iterations:
    content_forwarded = False  # ← 每迭代重置！
    async for chunk in stream_result:
        if has_content:
            content_forwarded = True  # 只对当前迭代有效
    # Guard: content_forwarded and iteration > 0
    # iteration 1 时 content_forwarded=False（当前迭代无 content）→ Guard 不触发
```

**修复**（Guard v3）: 新增 `any_content_ever_forwarded` 标志（loop 外初始化，只设 True 不重置）:
```python
any_content_ever_forwarded = False  # Loop 外，跨迭代

while iteration < max_iterations:
    content_forwarded = False  # 保留：per-iteration（错误显示用）
    async for chunk in stream_result:
        if has_content:
            content_forwarded = True
            any_content_ever_forwarded = True  # 永不重置

    if any_content_ever_forwarded and iteration > 0:
        break  # 任何之前迭代有 content → 不再执行更多工具
```

**测试**:
- 新增 `test_guard_breaks_when_previous_iteration_had_content`: iteration 0 有 content + tool_calls → iteration 1 只有 tool_calls → Guard break
- 保留其余 3 个 guard 测试不变
- 回归: `pytest tests/ -q` → **239 passed**

### Issue #9: Guard 方案整体设计缺陷 → 替换为 Buffer + Discard

**严重程度**: HIGH（架构级修正）
**发现步骤**: Step 1 Round 4 排障后分析
**修复状态**: 已修复

**现象**: Guard v1→v2→v3 的三次迭代暴露了 Guard 方案的根本矛盾：
- **Guard 目标**: 当 content 已流给用户后，阻止后续 tool_calls 以防 double-response
- **根本矛盾**: content 一旦流给用户（不可撤回），任何后续 tool_calls 都面临两难：执行 → double-response，不执行 → 工具链断裂
- **关键场景**: iteration 0 LLM 输出 "让我搜索一下" + list_knowledge_bases → Guard 必须放行 → iteration 1 LLM 只有 search_knowledge_base → Guard 必须放行（但此时 content 已流出）→ 无法用任何条件组合区分"合法多步工具链"与"即将 double-response"

**根因**: Guard 方案试图在"已流出 content"的约束下做事后补救，但问题的根源是 content 不应该在工具迭代期间流出。

**修复**（Buffer + Discard）:
```python
# 每迭代缓冲 content，不立即流给客户端
chunks: list[Any] = []
buffered_content: list[str] = []
async for chunk in stream_result:
    chunks.append(chunk)
    if chunk has content:
        buffered_content.append(chunk)  # 缓冲，不发送

rebuilt = stream_chunk_builder(chunks)
if finish_reason == "tool_calls":
    # 丢弃缓冲内容（如 "让我搜索一下"），执行工具
    logger.info("discarding %d buffered chunks", len(buffered_content))
    execute_tools(...)
    continue

# finish_reason == "stop" → 最终回答，flush 到客户端
for event in buffered_content:
    await queue.put(event)
break
```

**设计决策**:
- Codex 架构评审确认 Buffer + Discard 是唯一同时满足三个目标的方案：
  1. 工具永远能执行（多步工具链不受限）
  2. 无 double-response（content 只在 stop 时 flush）
  3. 流式 UX（最终回答仍然 chunk-by-chunk flush）
- 代价：工具迭代期间用户看不到实时文本流（已记录为 TD-007 技术债，可通过 provisional/commit 协议改进）

**测试**:
- 新增 3 个 buffer 测试替换 4 个 guard 测试:
  - `test_buffer_discard_content_on_tool_calls`: content + tool_calls → content 丢弃，工具执行
  - `test_buffer_multi_step_tools_all_execute`: 3 轮迭代多步工具链 → 全部执行
  - `test_buffer_normal_flow_flushes_on_stop`: 正常 stop → content flush
- 回归: `pytest tests/ -q` → **238 passed**

**关联文件**: `agent_service.py:146-240`, `tests/unit/test_agent_service.py`, `docs/improvement/tech-debt.md:TD-007`

---

### Issue #10: claude-max-proxy OAuth Token 过期 — 认证架构改造

**严重程度**: HIGH（阻塞所有依赖 LLM 的测试步骤）
**发现步骤**: Step 1 Round 5
**修复状态**: 进行中

**现象**: claude-max-proxy 返回 401 `"OAuth token has expired"`，agent-service 的所有 LLM 调用失败。

**排查过程**:

1. **Token 状态确认**:
   - `~/.claude-max-proxy.json` 中的 `expiresAt: 1771684345411`（2026-02-21 14:32 UTC）已过期 10+ 小时
   - Proxy 日志只有 `API error: 401`，无 refresh 相关日志

2. **Auto-refresh 机制分析**:
   - Proxy 的 `getOAuthTokens()` 实现了 on-demand refresh（请求时检查，非后台定时器）
   - `doRefreshToken()` 使用硬编码的 `client_id: 'ce88c5c9-...'` 和 TOKEN_URL `console.anthropic.com`
   - 刷新失败时**静默返回 null**（`catch(e) { return null; }`），无任何日志

3. **Refresh 失败根因 — 三组对比测试**:

   | 组合 | 结果 |
   |------|------|
   | OLD client_id + OLD url | `Client with id ... not found`（client_id 已废弃） |
   | NEW client_id + OLD url | `Refresh token not found or invalid` |
   | NEW client_id + NEW url | `Refresh token not found or invalid` |

   - **client_id 问题**: Claude Code CLI 在版本升级中从 `ce88c5c9-...` 迁移到 `9d1c250a-...`，Anthropic 废弃了旧 client_id → auto-refresh 从未成功
   - **refresh_token 问题**: OAuth refresh token 是**一次性的**（rotation 机制）。宿主机 CLI 在正常使用中刷新 token 时，旧 refresh_token 在 Anthropic 服务端被作废，proxy 持有的副本永久失效
   - TOKEN_URL 无关紧要：`console.anthropic.com` 和 `platform.claude.com` 行为相同

4. **macOS Keychain vs 文件**:
   - macOS 上 Claude Code CLI 以 Keychain 为 primary credential store
   - `~/.claude/.credentials.json` 文件**不会在 token refresh 时自动更新**
   - `claude auth status` 从 Keychain 读取（显示有效），但文件中的 token 可能已过期数天

**参考 Issue**:
- [#21765](https://github.com/anthropics/claude-code/issues/21765): Refresh token not used on remote/headless machines
- [#24317](https://github.com/anthropics/claude-code/issues/24317): Refresh token race condition with concurrent sessions
- [#22992](https://github.com/anthropics/claude-code/issues/22992): Device-code flow (RFC 8628) for headless — 尚未实现

**架构改造（进行中）**:

阶段 1 已完成 — proxy 只读模式 + 目录挂载 + 日志改进:
- `server.js`: `loadTokensFromFile()` 支持 CLI 嵌套格式 `claudeAiOauth`
- `server.js`: `getOAuthTokens()` 改为只读模式（移除 refresh/save，由 host CLI 管理）
- `server.js`: 启动 banner 和请求时日志显示 token 状态和刷新指引
- `docker-compose.yml`: 挂载 `~/.claude/` 目录（非文件）以支持 atomic rename
- `.env` / `.env.example`: `CLAUDE_TOKENS_PATH` → `CLAUDE_CREDENTIALS_DIR`

阶段 2 进行中 — 独立 OAuth 认证:
- 参考 opencode 实现，让 proxy 拥有自己的 OAuth 流程和专属 refresh_token
- 不再依赖外部 token 导出或文件同步
- 目标：与 opencode 一样自给自足，无需人工干预

**关联文件**: `claude-max-proxy/server.js`, `docker-compose.yml`, `.env`, `.env.example`

---

## 5. 时间线（问题与修复）

| 时间顺序 | 事件 | 结论/动作 |
|---|---|---|
| T1 | Step 1 Round 1: RAG 检索成功、第一段回答正确 | 工具链路可用 |
| T2 | 发现 double-response：第二轮工具调用失败 + 第二段矛盾回答 | 定位为 agent loop streaming bug |
| T3 | 根因定位：LLM 同时生成 content + tool_calls，loop 未检查 content_forwarded | Issue #1 |
| T4 | 修复 `agent_service.py:199` 增加 content_forwarded guard | 2 新增测试，237 全量回归通过 |
| T5 | 附带发现：knowledge base 返回 4 份文档，用户只上传了 1 份 | Issue #2 |
| T6 | 排查并确认 Open WebUI API Key 无效（401） | 更新 API Key，复测 200 OK |
| T7 | 观察到 Open WebUI 重启并排查 | 确认为 OOM（Issue #3） |
| T8 | Round 2 复测: 初次 build 未用 --no-cache，guard 代码不在容器中 | Docker build cache 问题 |
| T9 | Round 2 复测 2a: LLM 伪造 Tool Result 引用 | Issue #6，与 double-response 关联 |
| T10 | 确认 retrieval API 正常（KB ID 有效，返回 200） | 排除 422 为持续性问题 |
| T11 | 确认中文查询不匹配英文文档（embedding 跨语言不足） | Issue #4，增加英文查询指令 |
| T12 | Round 2 复测 2b: Guard 在 iteration 1 阻止工具执行 | Issue #5 |
| T13 | 日志确认 guard 触发: `"content already forwarded...breaking"` | LLM 混合文本+工具调用 |
| T14 | 修复: system prompt 增加 Tool Usage Protocol | 指导 LLM 先调工具再输出文本 |
| T15 | Round 3 复测: Guard 仍在 iteration 1 触发，工具未执行 | System prompt 软约束无效，Issue #7 |
| T16 | 修复: Guard v2 — `iteration > 0` 条件，首次工具调用不拦截 | 2 新增 + 1 重写测试，238 全量回归通过 |
| T17 | Round 4 复测: Guard v2 放行 iteration 0 工具，但后续迭代未拦截 | `content_forwarded` 按迭代重置，Issue #8 |
| T18 | 修复: Guard v3 — `any_content_ever_forwarded` 跨迭代追踪 | 1 新增测试，239 全量回归通过 |
| T19 | 用户发现 Guard v3 设计缺陷：阻断合法多步工具链 | Guard 方案根本矛盾暴露，Issue #9 |
| T20 | Codex 架构评审：确认 Buffer + Discard 为正确方案 | 同时建议 provisional/commit 协议作为长期改进 |
| T21 | 实施 Buffer + Discard 替换 Guard v1/v2/v3 | 3 buffer 测试替换 4 guard 测试，238 全量回归通过 |
| T22 | 记录 TD-007: provisional/commit SSE 协议（技术债） | Open WebUI 前端改造，非当前阻塞项 |
| T23 | Round 5: Buffer + Discard 确认工作（SSE 事件顺序正确，无 double-response） | Buffer 核心机制通过验证 |
| T24 | Round 5: search_knowledge_base 返回 422 | 改进错误处理，curl 直测 API 正常（200, score 0.77+） |
| T25 | Round 5: 发现 claude-max-proxy OAuth token 过期（401） | Issue #10 |
| T26 | 排查 auto-refresh: 硬编码 client_id 已废弃 + refresh_token 被 CLI 消费 | auto-refresh 从未成功过 |
| T27 | 三组对比测试确认 refresh 失败根因（client_id + token rotation） | client_id 和 refresh_token 双重失效 |
| T28 | 对比分析 opencode: 独立 OAuth 流程，自给自足 | 确定 proxy 需要独立 OAuth |
| T29 | Proxy 阶段 1 改造: 只读模式 + 目录挂载 + token 状态日志 | 临时方案，需 Keychain 同步 |
| T30 | 发现 macOS Keychain vs 文件不同步问题 | CLI refresh 只更新 Keychain，不写文件 |
| T31 | 决定阶段 2: 参考 opencode 为 proxy 实现独立 OAuth | 根本解决认证依赖问题 |

## 6. 当前状态与下一步

- 当前状态:
  - Issue #1（double-response bug）: **已修复**（Buffer+Discard，最终方案）。
  - Issue #2（API Key 无效）: **已修复**。
  - Issue #3（OOM 重启）: **已修复**（Docker 内存提升至 12GB）。
  - Issue #4（中英文 embedding 不匹配）: **已修复**（短期：英文查询指令）。
  - Issue #5（LLM 混合文本+工具调用）: **已修复**（Buffer+Discard 自动处理）。
  - Issue #6（LLM 伪造引用）: **间接修复**。
  - Issue #7（Guard 过于激进）: **已废弃**（Guard 方案整体替换）。
  - Issue #8（跨迭代追踪缺失）: **已废弃**（Guard 方案整体替换）。
  - Issue #9（Guard 方案设计缺陷）: **已修复**（Buffer+Discard 替换）。
  - Issue #10（OAuth token 过期）: **进行中**（阶段 1 只读模式完成，阶段 2 独立 OAuth 开发中）。
  - TD-007（provisional/commit SSE 协议）: 已记录为技术债，非阻塞。
  - Step 1 Round 5 部分通过（Buffer+Discard 确认，OAuth 阻塞），Round 6 待测。
- 下一步:
  1. 完成 proxy 独立 OAuth 改造（参考 opencode 实现），解除认证阻塞
  2. 复测 Step 1 Round 6，验证全链路（认证 + 工具调用 + RAG 来源 + 无 double-response）
  3. 排查 search_knowledge_base 422（可能是 LLM 参数格式问题，需 OAuth 修复后复现）
  4. 继续执行 Step 2~11 完整验收流程
