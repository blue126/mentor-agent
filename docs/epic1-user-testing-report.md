# Epic 1 人工验证测试报告（Open WebUI）

日期: 2026-02-20  
测试依据: `docs/user-testing-plan-epic1.md`  
测试环境: macOS + Docker + devcontainer/VS Code Port Forward 场景

## 1. 测试目标与范围

- 目标: 验证 Epic 1 核心链路可用（Open WebUI -> Agent Service -> LiteLLM -> Claude）。
- 范围: 按 `docs/user-testing-plan-epic1.md` 的 Step 1-5 执行并记录。
- 重点: 连接可达性、模型列表可见、对话可用、错误可观测、工具链路与流式事件兼容性。

## 2. 执行摘要（结论）

- 目前已达成: Open WebUI 可访问，连接可建立，模型可见，已可正常对话。
- 主要阻塞问题已清除: 网络可达、鉴权、模型路由、SSE 解析错误。
- 当前剩余体验问题: 首字延迟偏高（约 10-16 秒），已定位为流式前置非流式决策导致。

## 3. 按测试计划的结果记录

| 步骤 | 结果 | 备注 |
|---|---|---|
| Step 1 基础对话 | 通过 | 经过多轮修复后可正常收发 |
| Step 2 Mentor Persona 行为 | 待补测 | 本轮主要在联通性与稳定性排障 |
| Step 3 Tool Loop | 待补测 | 已修复流式解析问题，建议补跑 `echo` 用例 |
| Step 4 连续可用性 | 部分通过 | 已连续提问成功，但首字延迟偏高 |
| Step 5 失败兜底（可选） | 未执行 | 可后续专项验证 |

## 4. 故障现象、排错思路与修复过程

### 问题 A: Open WebUI 启动后无法访问

- 现象:
  - `docker compose ps` 显示 `open-webui` healthy，端口映射 `0.0.0.0:3000->8080` 正常，但浏览器访问失败。
- 排查思路:
  - 先验证容器与端口，再排查宿主机/IDE 端口劫持。
  - 发现 VS Code devcontainer 自动转发 3000 与宿主机直连冲突。
- 处理:
  - 明确两条访问路径不可混用（宿主机直连 vs VS Code forwarded URL）。
  - 关闭自动转发或改用非冲突端口策略。
- 结果:
  - Open WebUI 可稳定访问。

### 问题 B: Open WebUI Connection 添加后看不到模型

- 现象:
  - Connection 已保存，但模型列表为空。
- 根因:
  - Agent 服务未提供 OpenAI 兼容的 `GET /v1/models`。
- 修复:
  - 在 `app/routers/chat.py` 增加 `/v1/models` 与 `/v1/models/{model_id}`。
- 结果:
  - 模型列表可见。

### 问题 C: `401 Invalid or missing API key`（容器内请求）

- 现象:
  - `open-webui` 容器内访问 `http://agent-service:8100/v1/models` 返回 401。
  - 用户在 UI 填写了 `dev-token` 仍失败。
- 排查结论:
  - 非容器网络问题（`/health` 可达）。
  - `env_file` 加载顺序导致 `.env.example` 覆盖 `.env`。
- 修复:
  - 调整 `docker-compose.yml` 的 `env_file` 顺序，让 `.env` 最后覆盖。
- 结果:
  - 鉴权通过。

### 问题 D: 对话报错 `Litellm_proxyException - Connection error`

- 现象:
  - Open WebUI -> Agent 正常，但 Agent -> LiteLLM 失败。
- 根因:
  - Compose 中未运行 `litellm-claude-code`，或运行参数不满足要求。
- 修复:
  - 将 `litellm-claude-code` 加入同一 `docker-compose.yml`，并让 `agent-service` 依赖该服务。
- 结果:
  - 服务链路连通。

### 问题 E: LiteLLM 循环重启

- 现象:
  - 日志反复报:
    - `CLAUDE_TOKEN variable is not set`
    - `LITELLM_MASTER_KEY must start with 'sk-'`
- 排查结论:
  - `LITELLM_MASTER_KEY` 格式不合法（必须 `sk-` 前缀）。
  - 认证模式采用 Claude 订阅，应复用本机登录态而非 API token。
- 修复:
  - `LITELLM_KEY` 使用 `sk-...` 形式。
  - `litellm-claude-code` 挂载 `${HOME}/.claude:/home/claude/.claude` 复用宿主机登录态。
- 结果:
  - LiteLLM 服务可启动。

### 问题 F: `Invalid model name` / `LLM Provider NOT provided`

- 现象:
  - LiteLLM `/v1/models` 返回可用模型为 `sonnet/opus/haiku`。
  - 旧默认模型 `litellm_proxy/claude-sonnet-4-6` 无效。
  - 改成 `sonnet` 后，SDK 报 `LLM Provider NOT provided`。
- 根因:
  - 默认模型名与当前代理暴露模型不匹配。
  - LiteLLM Python SDK 调用需提供 provider 路由信息。
- 修复:
  - 默认模型调整为 `sonnet`。
  - 在 `llm_service.py` 中对无前缀模型自动规范为 `openai/<model>`（例如 `openai/sonnet`）用于 SDK 路由。
- 结果:
  - Provider 识别错误消失。

### 问题 G: Open WebUI 收不到消息，报 `JSON.parse unexpected character`

- 现象:
  - 无上游调用错误，但前端解析 SSE 失败。
- 根因:
  - heartbeat 使用 SSE 注释帧（`: keepalive`），部分客户端误当 JSON 解析。
- 修复:
  - 将 heartbeat 改为 JSON 格式的 `data: { ... }` chunk。
- 结果:
  - 可正常流式接收消息。

## 5. 代码与配置改动清单

- `mentor-agent-service/docker-compose.yml`
  - 新增 `open-webui` 与 `litellm-claude-code` 服务。
  - 调整 `env_file` 顺序（`.env` 覆盖 `.env.example`）。
  - `agent-service` 增加 `depends_on: litellm-claude-code`。
  - `litellm-claude-code` 挂载改为 `${HOME}/.claude:/home/claude/.claude`。
- `mentor-agent-service/app/routers/chat.py`
  - 新增 `GET /v1/models`。
  - 新增 `GET /v1/models/{model_id}`。
- `mentor-agent-service/app/config.py`
  - 默认 `litellm_model` 调整为 `sonnet`。
- `mentor-agent-service/app/services/llm_service.py`
  - 新增 `_normalize_model_for_litellm`，将无前缀模型映射为 `openai/<model>`。
- `mentor-agent-service/app/utils/sse_generator.py`
  - heartbeat 从注释帧改为 JSON 数据帧。
- `mentor-agent-service/.env.example`
  - `LITELLM_MODEL` 更新为 `sonnet`。
  - 补充 `CLAUDE_TOKEN` 示例项（历史排障中加入，订阅模式可不使用）。

## 6. 关键概念/判断问题记录（来自测试过程）

- 问题: “Docker-in-Docker 环境要在宿主机执行命令吗？”
  - 结论: 若用宿主机浏览器访问 `localhost`，应在宿主机启动对应服务；否则需多层端口转发。
- 问题: “Open WebUI 手动填写 API Key 为何不覆盖 `.env`？”
  - 结论: UI 中 key 是客户端请求头，`.env` 是服务端校验值；两者需一致，互不覆盖。
- 问题: “`sk-` 前缀是谁规定的？”
  - 结论: LiteLLM 对 `LITELLM_MASTER_KEY` 的格式要求（日志已明确提示）。
- 问题: “`openai/sonnet` 是否错误归属？”
  - 结论: 该前缀用于 LiteLLM provider 路由（OpenAI-compatible adapter），不代表模型厂商归属变更。
- 问题: “什么是非流式？所有回答都应流式吗？”
  - 结论: 非流式=整段生成后一次性返回；当前实现存在流式前置非流式工具决策，导致首字延迟，设计上应优化为先流式再工具化。

## 7. 当前状态与后续建议

- 当前已达成:
  - Open WebUI 可访问。
  - 模型可见并可对话。
  - 关键错误（鉴权、模型路由、SSE 解析）已清除。
- 当前待优化:
  - 首字延迟（TTFB）仍偏高，简单问句约 10-16 秒。
- 建议下一步:
  - 将 `run_agent_loop_streaming` 改为“fast path 优先”：先流式直答，明确命中工具场景再进入工具循环。
  - 对 Step 2/3/5 做补测并回填结果表，完成 Epic 1 闭环验收。
