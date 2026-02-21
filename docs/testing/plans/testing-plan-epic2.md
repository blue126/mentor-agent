# Epic 2 完整人工验证方案（知识摄入与学习规划）

版本: v2.0  
目标: 在 Epic 2 全部实现后，用一轮人工验证确认 2.1~2.4 端到端可用，并可作为 Epic 3 的输入基线

## 1) 测试范围（完整 Epic 2）

- Story 2.1: `search_knowledge_base`（RAG 检索）
- Story 2.2: 知识图谱数据模型与服务（SQLite + NetworkX）
- Story 2.3: `generate_learning_plan`（学习计划生成并落库）
- Story 2.4: `extract_concept_relationships`（关系抽取并写入图谱）

不在本计划内：Epic 3 的 Teach Me 编排与前置检查对话策略（只做输入可用性确认，不做行为验收）。

## 2) 环境准备

- Open WebUI 正常可用，并已连接 `agent-service`（`/v1` 端点可访问）。
- 选择可用模型（建议固定 1 个模型做整轮验证）。
- 上传至少 1 份结构清晰的 PDF（建议带目录与章节，例如教材/技术书）。
- `mentor-agent-service` 可执行 pytest。
- 准备 1 份测试记录文档（建议后续写入 `docs/testing/reports/testing-report-epic2.md`）。

## 3) 20-30 分钟用户侧验收流程（Open WebUI）

### Step 1: RAG 基础检索（2.1）

- 输入：`请基于我上传的资料，解释“闭包”，并给出来源依据。`
- 通过标准：
  - 能返回基于资料的回答（不是纯泛化）；
  - 回答中可见来源痕迹（文档名/章节/片段语义）；
  - 会话不中断。

### Step 2: RAG 连续追问一致性（2.1）

- 输入：`把上面的解释压缩成 3 个学习要点，并标注每个要点对应的资料依据。`
- 通过标准：
  - 保持上下文连续；
  - 仍体现资料约束，不出现明显“脱离上传文档”的答复。

### Step 3: 学习计划生成（2.3）

- 输入：`请根据我上传的资料生成学习计划，按 chapter/sections 结构输出。`
- 通过标准：
  - 返回结构化结果（JSON 或等价结构）；
  - 至少包含 chapter + sections 层级；
  - 结构可读且与文档目录语义大致一致。

### Step 4: 学习计划可追问性（2.3）

- 输入：`根据刚才计划，告诉我 next step 是什么，为什么先学它。`
- 通过标准：
  - 能基于已生成计划回答下一步；
  - 解释顺序合理（非随机建议）。

### Step 5: 关系抽取（2.4）

- 期望行为（产品侧）：学习计划生成后自动触发关系抽取（无需用户二次发起）。
- 人工验证方式（测试侧）：
  - 先在聊天界面等待 5-15 秒，不输入新消息，观察是否自动出现“关系抽取结果”文本（例如含 `prerequisite` / `related` 或“前置/关联关系”）；
  - 若界面支持状态流，观察是否自动出现类似 `Running extract_concept_relationships...` 的提示（可选，不作为必须条件）；
  - 若未自动触发，再发送：`请从当前学习计划中抽取 prerequisite 和 related 关系。`（作为兜底触发语句，便于稳定验收）。
- 通过标准：
  - 自动或兜底触发至少一种方式成功；
  - 返回关系结果，至少出现两类关系中的一种；
  - 若返回两类关系更佳；
  - 关系描述与领域常识不明显冲突。

### Step 6: 关系可用性验证（2.4 -> 3.x 输入）

- 输入：`基于你刚才抽取的关系，列出“学习 X 前建议先掌握什么”。`
- 说明：
  - 如果 Step 5 是自动触发成功，Step 6 直接验证自动产出的关系是否可被后续问答消费。
  - 如果 Step 5 依赖兜底手动触发，Step 6 只验证“关系数据可用性”，并在备注标记为“manual-trigger path passed”。
- 通过标准：
  - 能引用前置关系给出可执行建议；
  - 与 Step 5 的关系结果一致（至少能对上 1-2 个具体关系）。

### Step 7: Fail Soft（2.1，建议做）

- 临时模拟 RAG 检索不可用后，输入：`再检索一次并总结。`
- 推荐模拟方式（用户可执行，不中断聊天界面）：
  - 将 `mentor-agent-service/.env` 中 `OPENWEBUI_BASE_URL` 临时改为不可达地址（如错误端口），重启 `agent-service` 后执行 Step 7。
- 参考命令（按当前环境自行调整，完成后务必恢复）：
  ```bash
  # 1) 备份当前配置
  cp mentor-agent-service/.env mentor-agent-service/.env.bak

  # 2) 将 OPENWEBUI_BASE_URL 临时改为不可达地址（示例端口 65535）
  # 手工编辑 .env，或用你熟悉的编辑器修改这一行：
  # OPENWEBUI_BASE_URL=http://open-webui:65535

  # 3) 重启 agent-service 使配置生效
  docker compose -f mentor-agent-service/docker-compose.yml up -d --force-recreate agent-service

  # 4) 执行 Step 7 对话测试后，恢复配置并重启
  mv mentor-agent-service/.env.bak mentor-agent-service/.env
  docker compose -f mentor-agent-service/docker-compose.yml up -d --force-recreate agent-service
  ```
- 通过标准：
  - 返回友好降级提示；
  - 服务不中断，可继续对话。
  - 环境恢复后，RAG 查询再次可用。

## 4) 开发者侧验证（数据与回归）

### Step 8: Epic 2 相关测试集

- 在 `mentor-agent-service` 目录运行：
  - `python -m pytest tests/unit/test_graph_repo.py tests/unit/test_graph_service.py tests/integration/test_graph_integration.py tests/integration/test_migration.py -q`
- 通过标准：全部通过。

### Step 9: 全量回归

- 运行：`python -m pytest tests/ -q`
- 通过标准：全量通过（基线数值允许随新增测试增长）。

### Step 10: 数据落库抽检

- 抽检 SQLite：
  - 表存在：`topics`, `concepts`, `concept_edges`
  - 字段存在：`created_at`、关系字段、topic/concept 主外键
- 通过标准：结构与 Story 2.2 设计一致。

### Step 11: 计划与关系数据抽检（2.3/2.4）

- 抽样确认：
  - 计划生成后有对应 topic/concept 数据（非仅对话文本）
  - 关系抽取后 `concept_edges` 有新增记录
- 通过标准：对话结果与 DB 状态一致（可追溯）。

## 5) 结果记录模板

| 步骤 | 结果 | 证据 | 备注 |
|---|---|---|---|
| Step 1 | 通过/失败 | 对话截图/文本 | |
| Step 2 | 通过/失败 | 对话截图/文本 | |
| Step 3 | 通过/失败 | 输出结构截图/文本 | |
| Step 4 | 通过/失败 | 对话截图/文本 | |
| Step 5 | 通过/失败 | 关系输出截图/文本 | |
| Step 6 | 通过/失败 | 对话截图/文本 | |
| Step 7(建议) | 通过/失败 | 降级提示截图/文本 | |
| Step 8 | 通过/失败 | pytest 输出 | |
| Step 9 | 通过/失败 | pytest 输出 | |
| Step 10 | 通过/失败 | DB 抽检记录 | |
| Step 11 | 通过/失败 | DB + 对话对照记录 | |

## 6) Epic 2 完成判定

- 必须通过：Step 1~6、Step 8~11
- 建议通过：Step 7（Fail Soft）
- 判定规则：
  - 必须步骤全部通过 => Epic 2 可判定为完工并进入 Epic 3 主开发
  - 若 Step 3/5/11 任一步失败 => 不建议进入 Epic 3（说明计划/关系落库链路仍不稳定）

## 7) 常见失败定位

- Step 1/2 失败：优先看 `search_knowledge_base` 工具注册与 Open WebUI 检索 API 连通性。
- Step 3/4 失败：优先看 `generate_learning_plan` 工具输出结构与落库调用链。
- Step 5/6 失败：优先看 `extract_concept_relationships` 输出格式与 `graph_service.add_edge` 调用。
- Step 8/9 失败：先修复单测/集测，再做人工回归。
- Step 10/11 失败：优先排查 migration、repo/service 分层、commit 后内存图重建路径。
