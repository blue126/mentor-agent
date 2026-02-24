# 双路径架构迁移评估报告

Status: Implemented
Baseline Profile: subscription (claude-max-proxy)
Last validated: 2026-02-23

## 1. 背景

### 1.1 Epic 1 Step 3 根因分层

Epic 1 验证过程中，工具调用（Step 3）经历了多层问题，按排查顺序：

| 层级 | 问题 | 根因 | 解决状态 |
|------|------|------|---------|
| L1 上游语境污染 | 模型回复"没有 echo 工具"，暴露 `Task/Bash/Read` 等外部工具域 | `litellm-claude-code` provider 将消息合并为文本 prompt，`allowed_tools=[]` 导致 Claude Code 内置工具语境混入 | 切换上游后消除 |
| L2 模型路由不匹配 | `LLM Provider NOT provided` / `404 Not Found` | 不同上游对 model 前缀要求不同；`_normalize_model_for_litellm()` 未按 `LITELLM_BASE_URL` 区分路由 | 已修复（Epic 1 Story 1.6） |
| L3 工具参数续传缺失 | `UnsupportedParamsError: Anthropic doesn't support tool calling without tools= param` | stream 收尾请求未携带 `tools`/`tool_choice`，Anthropic API 拒绝 | 已修复（Epic 1 Story 1.6） |
| L4 工具循环不收敛 | `Tool use loop reached maximum iterations (10)` | L2 + L3 叠加导致循环无法正常终止 | L2/L3 修复后自动解决 |

### 1.2 已通过的最终链路 vs 历史失败链路

| 链路 | 状态 | 说明 |
|------|------|------|
| Open WebUI → agent-service → **claude-max-proxy** → Anthropic OAuth | **通过（当前基线）** | Step 1-5 全通过，工具循环 2 轮收敛 |
| Open WebUI → agent-service → **Anthropic API 直连** | **通过（回退可用）** | L2/L3 修复后 Step 3 通过 |
| Open WebUI → agent-service → **litellm-claude-code** | **未通过（非基线）** | L1 上游语境污染未解决；工具调用不可用 |

### 1.3 迁移动机

基于上述验证结果，项目需要从"单一 litellm-claude-code 上游"迁移到"双路径架构"：以已通过验证的 claude-max-proxy 为基线，保留 litellm-claude-code 为非基线可选路径。

本文档评估该迁移所需的完整改动范围。

## 2. 目标架构

### 双路径架构

```
                                 ┌─ [Baseline] claude-max-proxy → Anthropic OAuth (subscription)
Open WebUI → Agent Service ──────┤
                                 └─ [Fallback] 直连 / 通用 litellm proxy → Anthropic/OpenAI/Gemini API (api)
```

两条路径共享同一个 agent-service tool loop，通过 `.env` 配置切换。

### claude-max-proxy 部署方式

> **当前状态：** 验证阶段 claude-max-proxy 以宿主机进程运行，agent-service 通过 `host.docker.internal:3456` 访问。
>
> **目标状态：** 正式实施时 claude-max-proxy 必须纳入 docker-compose 编排，与 agent-service、open-webui 等组件统一管理。agent-service 通过 Docker 内部网络 `http://claude-max-proxy:3456` 访问。

### 路径定义

| 路径 | 上游代理 | 认证方式 | 工具调用机制 | 定位 |
|------|---------|---------|-------------|------|
| **subscription profile** | claude-max-proxy | OAuth token | XML 注入 + 解析 | **当前基线** |
| **api profile** | 直连 / 通用 litellm proxy | API key | 原生 `tools` 参数 | 回退 / 对照验证 |

**注意区分：**
- **litellm-claude-code**：Claude subscription 专用的 CLI wrapper，工具调用受限，当前为非基线。
- **通用 litellm proxy**：标准 LiteLLM 代理，支持多 provider API key 接入，工具调用正常。二者不是同一个东西。

### 关键决策

- **确立 subscription profile 为当前基线**——零成本，已验证可用。
- **保留 litellm-claude-code 为非基线路径**——降级为 Claude subscription 相关的可选路径（非基线），不移除。api profile 的上游为直连或通用 litellm proxy，与 litellm-claude-code 无关。
- **保留 litellm Python 库**——作为 HTTP 客户端，与上游代理解耦，两条路径共用。
- **配置变量 `LITELLM_*` 暂不重命名**——收益仅为命名一致性，但触发 ~27 个文件 ~55 处机械替换，噪音高。降级为 P2，待有合适窗口时再执行。
- **Agent Service 的 tool loop 核心循环框架保留**——工具注册、执行、SSE streaming 不动。参数续传（stream 收尾时续传 `tools`/`tool_choice`）与模型路由兼容策略已在 Epic 1 中调整完毕。

## 3. 术语表

以下术语在本项目文档中统一使用，旧称不再作为实现依据：

| 统一术语 | 含义 | 废弃旧称 |
|---------|------|---------|
| subscription profile | 通过 claude-max-proxy + OAuth token 接入 Claude 的路径 | "litellm-claude-code 路径"、"订阅适配器" |
| api profile | 通过 API key 接入 LLM provider 的路径（可经 litellm proxy 或直连） | "Anthropic 直连"、"API 路径" |
| upstream proxy | agent-service 与 LLM 之间的代理层（claude-max-proxy 或 litellm proxy） | "LiteLLM 代理"、"adapter" |
| baseline | 当前默认推荐的生产/验证路径 | — |
| fallback | 基线不可用时的回退路径 | — |

## 4. 基线声明（可直接引用）

> **当前生产基线路径为：Open WebUI → agent-service → claude-max-proxy → Anthropic OAuth；除非文档明确标注"非基线"，否则均以此路径为准。**

> **API profile 仅作为回退路径与对照验证路径，不代表当前默认生产实现，也不应作为新功能设计的首选前提。**

> **agent-service 负责编排、会话与业务语义；upstream proxy 负责上游接入与认证转发，二者通过明确接口契约解耦，禁止跨边界承担对方职责。**

## 5. 全局影响总览

| 层级 | 文件数 | litellm 引用数 | 改动性质 |
|------|--------|---------------|---------|
| 规划文档（_bmad-output/planning-artifacts） | 4 | ~22 | 架构定义修改：基线切换 + 双路径描述 |
| 实现文档（_bmad-output/implementation-artifacts） | 9 | ~56 | 实现规范修改：上游机制说明更新 |
| 业务代码 + 配置 | 6 | ~15 | 本次迁移不新增业务逻辑改动；沿用 Epic 1 已完成的兼容修复 |
| 测试代码 | 8 | ~40 | 同上；变量重命名降级为 P2 |
| **合计** | **27** | **~133** | — |

## 6. 设计文档影响（_bmad-output/）

### 6.1 高影响（需要实质性修改）

#### `planning-artifacts/architecture.md` — 11 处引用

- `litellm-claude-code` 被标为**硬约束** → 改为双路径架构，subscription profile 为基线
- 数据流图为单路径 → 改为双路径图
- 风险评估"litellm tool_use 兼容性" → 改为"OAuth token 不支持原生 tools 参数 + 上游路径一致性"
- **新增：** 术语表、基线声明、元信息头

#### `implementation-artifacts/1-2-openai-compatible-api-basic-llm-proxy.md` — 31 处引用

- LiteLLM 调用模式 / streaming 代码示例 → 更新为路径无关的 `litellm.acompletion()` 说明
- docker-compose 中 litellm-claude-code 服务配置 → 改为双服务配置
- 所有硬编码 `litellm-claude-code` 上游 → 按 profile 描述

#### `implementation-artifacts/1-3-tool-use-loop-engine.md` — 15 处引用

- "litellm 自动做 Claude↔OpenAI 格式转换"说明 → 区分两条路径的工具调用机制：
  - subscription profile：claude-max-proxy XML 注入 + 解析
  - api profile：litellm 原生 `tools` 参数透传

### 6.2 中影响（局部段落修改）

| 文件 | 引用数 | 改动说明 |
|------|--------|---------|
| `implementation-artifacts/1-1-project-skeleton-and-dev-environment.md` | 6 | docker-compose 占位符、依赖列表、.env 模板 → 双路径配置 |
| `implementation-artifacts/1-4-sse-intermediate-status.md` | 12 | streaming 行为描述 → 补充 subscription profile 工具调用时强制同步的限制 |
| `planning-artifacts/epics.md` | 5 | 风险评估"litellm-claude-code 关键未知项" → 改为"上游适配器一致性 + 双路径回归" |
| `planning-artifacts/prd.md` | 4 | 系统架构图、部署方案 → 双路径架构描述 |

### 6.3 低影响（个别词替换或不改）

| 文件 | 引用数 | 改动说明 |
|------|--------|---------|
| `implementation-artifacts/1-5-system-prompt-and-mentor-persona.md` | 1 | "LiteLLM 薄封装" → "LLM 客户端薄封装" |
| `planning-artifacts/implementation-readiness-report-2026-02-19.md` | 2 | 部署架构描述更新；变量名保留不改 |
| `implementation-artifacts/2-2-knowledge-graph-data-model-and-service.md` | 1 | commit message 引用，不改 |
| `implementation-artifacts/2-1-rag-knowledge-base-search.md` | 0 | 不需要改 |
| `implementation-artifacts/epic-1-retro-2026-02-19.md` | 0 | 历史记录，不改 |
| `implementation-artifacts/sprint-status.yaml` | 0 | 不需要改 |

### 6.4 其他文档

| 文件 | 改动说明 |
|------|---------|
| `docs/testing/reports/testing-report-epic1.md` | 添加元信息头 + 基线声明 + 弃用路径说明 |
| `docs/subscription-provider-feasibility-report.md` | 升级为决策记录：附状态标签 `Adopted with constraints` |
| `docs/testing/plans/testing-plan-epic1.md` | 按 profile 分区验收步骤 |
| `plan.md` | 架构图、容器编排、.env、部署顺序 → 引用 SSOT，不重复描述 |

## 7. 代码影响（mentor-agent-service/）

### 7.1 基础设施

| 文件 | 改动 |
|------|------|
| `docker-compose.yml` | `litellm-claude-code` 服务保留但标注为非基线；**新增 `claude-max-proxy` 服务定义（待实施：当前以宿主机进程运行，需容器化纳入编排）** |
| `.env.example` | 变量名保留 `LITELLM_*`；提供双 profile 配置示例（subscription 为默认，api 为注释） |

### 7.2 业务代码

当前阶段不做 `LITELLM_*` → `LLM_*` 重命名。业务代码和测试代码无需改动。

### 7.3 依赖文件

| 文件 | 改动 |
|------|------|
| `pyproject.toml` | litellm 依赖保留（两条路径共用） |
| `requirements.txt` | 同上 |

### 7.4 P2：配置变量重命名（暂缓）

将 `LITELLM_*` → `LLM_*` 的全量重命名降级为 P2。涉及 config.py、llm_service.py、agent_service.py、chat.py 及 10 个测试文件共 ~55 处引用。收益仅为命名一致性，待有合适窗口时再执行。

## 8. 语义级变更清单

以下变更不是简单的文字替换，需要理解上下文后修改：

| # | 变更项 | 涉及文件 | 说明 |
|---|--------|---------|------|
| S1 | 硬约束 → 双路径 | architecture.md | `litellm-claude-code` 从硬约束降级为非基线可选路径；新增 `claude-max-proxy` 为基线 |
| S2 | 数据流图 | architecture.md, prd.md | 单路径图 → 双路径图（baseline + fallback） |
| S3 | tool calling 机制 | Story 1.3 | 区分两条路径的工具调用机制（XML 注入 vs 原生 tools 参数） |
| S4 | 风险评估 | architecture.md, epics.md | "litellm tool_use 兼容性" → "OAuth token 限制 + 上游适配器一致性" |
| S5 | ~~配置变量名~~ | ~~所有含 env 示例的文件~~ | ~~`LITELLM_*` → `LLM_*`~~ **降级为 P2，暂不执行** |
| S6 | streaming 限制 | Story 1.2, 1.4 | subscription profile 带工具时 claude-max-proxy 强制同步模式 |
| S7 | 旧路径降级标注 | 所有提及 litellm-claude-code 的文件 | 标注为 `[Non-baseline]` 或 `[Deprecated as default]`，保留为可选 |

## 9. 不需要修改的部分

以下模块与上游代理层完全解耦，迁移不影响：

- Agent Service 的 tool loop 核心循环框架（`agent_service.py`）——注：参数续传与模型路由兼容已在 Epic 1 中调整完毕，本次迁移无需再改
- 工具注册表和工具实现（`tools/`）
- SSE streaming 生成器（`utils/sse_generator.py`）
- 系统提示词管理（`prompt_service.py`）
- 数据库模型和 ORM（`models.py`）
- Open WebUI RAG 集成（`search_knowledge_base_tool.py`）

## 10. 已知限制与风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| OAuth token 无官方 SLA，Anthropic 可随时变更策略 | subscription profile 可能突然不可用 | 保留 api profile 作为即时回退 |
| claude-max-proxy 的 XML 解析在边界情况下可能失败 | 复杂工具参数（嵌套 JSON、特殊字符）可能解析错误 | 补充集成测试覆盖边界情况 |
| subscription profile 带工具时强制同步 | TTFB 高于 api profile | 用 SSE status 事件缓解用户感知 |
| 双路径增加维护和测试成本 | 每次变更需双路径回归 | 统一验收用例集，按 profile 标注适用范围 |

## 11. 验收标准

### 文档验收

- [ ] 所有文档顶部有元信息头（Status / Baseline Profile / Last validated）
- [ ] `litellm-claude-code` 在文档中不再标记为硬约束或默认路径
- [ ] `litellm-claude-code` 相关内容标注为 `[Non-baseline]`，保留但不删除
- [ ] 术语表在 architecture.md 中建立，各文档使用统一术语

### 代码验收

- [ ] 全部单元测试和集成测试通过
- [ ] docker-compose 包含 claude-max-proxy（基线，容器化）和 litellm-claude-code（非基线，可选启动）
- [ ] agent-service 通过 Docker 内部网络 `http://claude-max-proxy:3456` 访问基线上游（不再依赖 `host.docker.internal`）
- [ ] `.env` 默认指向 subscription profile

### Epic 1 验收基线

- [ ] **基线链路 Open WebUI → agent-service → claude-max-proxy 下 Step 1-5 全通过，才算 Epic 1 验收通过**
- [ ] 非基线链路（api profile / litellm-claude-code）的测试结果仅作为对照参考，不作为 Epic 1 验收的通过条件

### 功能验收

测试条件：同一 profile、同一模型（claude-sonnet-4-6）、同一提示词集、连续执行。

- [ ] subscription profile：`echo` 工具连续 20 次调用，成功率 >= 90%
- [ ] subscription profile：`search_knowledge_base` 连续 10 次调用，成功率 >= 85%
- [ ] api profile：`echo` 工具连续 20 次调用，成功率 = 100%
- [ ] profile 切换：修改 `.env` 后重启，两条路径均可正常工作

## 附录 A：配置 Profile 示例

### Subscription Profile（基线）

```env
LITELLM_BASE_URL=http://claude-max-proxy:3456/v1
LITELLM_KEY=sk-dev-key
LITELLM_MODEL=openai/claude-sonnet-4-6
```

### API Profile（回退）

```env
LITELLM_BASE_URL=https://api.anthropic.com
LITELLM_KEY=sk-ant-xxx
LITELLM_MODEL=anthropic/claude-sonnet-4-6
```

### API Profile via LiteLLM Proxy（可选）

```env
LITELLM_BASE_URL=http://litellm-claude-code:4000/v1
LITELLM_KEY=your-litellm-key
LITELLM_MODEL=sonnet
```

注：api profile via litellm proxy 仅适用于纯对话场景或未来 litellm-claude-code 修复 tool calling 后的场景。当前该路径的自定义工具调用不稳定。
