# Epic 1 人工验证测试报告（Open WebUI）

日期: 2026-02-20  
测试依据: `docs/user-testing-plan-epic1.md`  
测试环境: macOS + Docker + devcontainer/VS Code Port Forward

## 1. 测试目标与范围

- 目标: 验证 Epic 1 核心链路可用（Open WebUI -> Agent Service -> LiteLLM/Anthropic -> Tool Loop）。
- 范围: 按 `docs/user-testing-plan-epic1.md` 的 Step 1-5 执行，记录故障、排查、修复与结论。

## 2. 结果总览

| 步骤 | 结果 | 备注 |
|---|---|---|
| Step 1 基础对话 | 通过 | 链路可用，能正常回复 |
| Step 2 Mentor Persona 行为 | 通过（最新复测） | 模型先做前置知识检查，未直接给定义 |
| Step 3 Tool Loop | 通过 | 可见 Thinking/Running，`echo` 结果正确返回 |
| Step 4 连续可用性 | 通过（有文本泄露风险） | 会话连续可用，但一次回复末尾出现 `<system-reminder>` 非业务文本 |
| Step 5 失败兜底（可选） | 通过 | 上游不可用时返回可理解错误，服务不崩溃 |

## 3. 分步骤测试与排障记录

### Step 1: 基础对话（通过）

- 测试动作:
  - 访问 Open WebUI，配置连接到 `agent-service`。
  - 发送基础问句验证可回复。
- 主要问题与处理（按发生顺序）:
  - **Open WebUI 无法访问（端口冲突）**
    - 现象: 容器 healthy 且映射 `3000->8080`，浏览器仍打不开。
    - 排查命令:
      ```bash
      docker compose -f docker-compose.yml ps
      docker compose -f docker-compose.yml logs open-webui --tail 120
      docker port open-webui
      ```
    - 关键输出:
      ```text
      open-webui ... Up (healthy) ... 0.0.0.0:3000->8080
      Uvicorn running on http://0.0.0.0:8080
      ```
    - 结论: VS Code 自动转发 3000 与宿主机访问路径冲突。
    - 处理: 统一访问路径（宿主机直连），关闭冲突转发。
  - **连接后看不到模型**
    - 根因: Agent 未提供 `/v1/models`。
    - 代码改动: `mentor-agent-service/app/routers/chat.py` 新增 `GET /v1/models` 与 `GET /v1/models/{model_id}`。
  - **容器内 401 鉴权失败**
    - 排查命令:
      ```bash
      docker exec -it open-webui sh -lc "curl -i http://agent-service:8100/health"
      docker exec -it open-webui sh -lc "curl -i -H 'Authorization: Bearer dev-token' http://agent-service:8100/v1/models"
      ```
    - 关键输出:
      ```text
      /health -> 200
      /v1/models -> 401 Invalid or missing API key
      ```
    - 根因: `env_file` 顺序导致 `.env.example` 覆盖 `.env`。
    - 代码改动: `mentor-agent-service/docker-compose.yml` 调整 `env_file` 顺序。

### Step 2: Mentor Persona 行为（通过）

- 测试输入: `什么是闭包？`
- 观察结果:
  - 模型先反问了前置知识（符合预期方向）。
  - 但未等待用户反馈即给出完整定义和示例（偏离“纯引导式”）。
- 最新复测结果:
  - 输入 `什么是闭包`
  - 模型先询问语言与作用域基础（前置检查），未直接输出闭包定义。
- 判定: 通过（最新复测）。

### Step 3: Tool Loop（通过）

- 测试目标:
  - 输入 `用 echo 工具返回 hello tool loop`
  - 期望看到 Thinking/Running + 最终结果包含 `hello tool loop`。

- 问题排查路径（按时间顺序）:
  - **阶段 A：工具语境混入（失败）**
    - 现象: 模型声称没有 `echo`，并列出 `Task/Bash/Read/...`。
    - 后端核验命令:
      ```bash
      docker exec -it mentor-agent-service sh -lc "python - <<'PY'
      from app.tools import registry
      print(registry.list_tools())
      PY"
      ```
    - 关键输出:
      ```text
      ['echo', 'search_knowledge_base', 'list_knowledge_bases']
      ```
    - 结论: 后端工具已注册，问题在上游工具语境。
  - **阶段 B：切换到 API 路径做 A/B（继续定位）**
    - 目标: 排除 Claude Code 订阅运行时工具语境干扰。
    - 结果: 外部工具域问题消失，但出现不收敛/404/UnsupportedParams 等新问题。
  - **阶段 C：模型路由与参数一致性修复（通过）**
    - 关键问题 1: 无前缀模型名在 Anthropic 路径下路由异常。
      - 代码改动: `mentor-agent-service/app/services/llm_service.py` 停止自动改写无前缀模型名。
    - 关键问题 2: Anthropic 工具后续请求要求继续携带 `tools`。
      - 典型报错:
        ```text
        litellm.UnsupportedParamsError: Anthropic doesn't support tool calling without tools= param specified
        ```
      - 代码改动:
        - `mentor-agent-service/app/services/llm_service.py`
          - `stream_chat_completion(...)` 增加 `tools` / `tool_choice` 参数并透传。
        - `mentor-agent-service/app/services/agent_service.py`
          - 工具循环后流式收尾调用补传 `tools=tools`、`tool_choice="auto"`。
  - **阶段 D：subscription 路径回归（通过）**
    - 拓扑: Open WebUI -> `agent-service` -> `claude-max-proxy`（OAuth 订阅）
    - 关键配置:
      ```env
      LITELLM_BASE_URL=http://host.docker.internal:3456/v1
      LITELLM_MODEL=openai/claude-sonnet-4-6
      ```
    - 验证结果:
      - 工具列表请求返回项目工具边界：`echo / search_knowledge_base / list_knowledge_bases`
      - `用 echo 工具返回 hello tool loop` 返回成功（Thinking/Running + 正确结果）

- 诊断日志证据（修复后）:
  ```text
  tool-loop(stream) iteration=1
  tool-loop(stream) finish_reason=tool_calls
  tool-loop(stream) calling tool name=echo args={"message": "hello tool loop"}
  tool-loop(stream) tool_result name=echo result=hello tool loop
  tool-loop(stream) iteration=2
  tool-loop(stream) finish_reason=stop
  ```

- 最终用户可见结果:
  ```text
  💭 Thinking...
  🔧 Running echo...
  The echo tool confirmed: hello tool loop
  ```

- 判定: 通过。

- 外部依赖说明:
  - `litellm-claude-code` 路径曾出现工具语境不一致，不适合作为本轮验收 subscription 路径。
  - `claude-max-proxy` 路径在本轮已通过 Step 3 验证。

### Step 4: 连续可用性（通过）

- 测试输入: `继续解释上一步你做了什么`
- 结果: 同会话持续可回复，会话未中断。
- 备注:
  - 在 Step 3 未稳定前，Step 4 内容曾被“无 echo 工具”语义污染；在 Step 3 修复后该影响已消除。
  - 最新一次回复末尾出现 `<system-reminder>...</system-reminder>` 非业务文本，需作为输出清洗问题单独跟踪。

### Step 5: 失败兜底（通过，早期已覆盖）

- 覆盖方式: 早期未启动 LiteLLM/上游不可达时触发。
- 关键输出:
  ```text
  Error: LLM service unavailable — ... Connection error
  ```
- 判定: 返回可理解错误且系统未崩溃，符合兜底要求。

## 4. 关键概念/判断问题记录

- 问题: Docker-in-Docker 场景命令应在宿主机还是容器执行？
  - 结论: 若用宿主机浏览器访问 `localhost`，服务应在宿主机侧可达；避免与 VS Code 自动转发冲突。
- 问题: Open WebUI 里手填 API Key 为什么不覆盖 `.env`？
  - 结论: UI key 是客户端请求头；`.env` 是服务端校验值，二者互不覆盖，必须一致。
- 问题: `sk-` 前缀是谁要求的？
  - 结论: LiteLLM 对 `LITELLM_MASTER_KEY` 的格式要求。
- 问题: `openai/sonnet` 是否表示模型归属 OpenAI？
  - 结论: 不是；那是 LiteLLM provider 路由前缀，不代表模型厂商归属。
- 问题: “所有回答都该流式吗？”
  - 结论: 交互体验上应尽量先流式输出；非流式前置决策会拉高首字延迟。

## 5. 时间线（问题与修复）

| 时间顺序 | 事件 | 结论/动作 |
|---|---|---|
| T1 | Open WebUI 可访问但页面打不开 | 定位为端口转发冲突，统一访问路径 |
| T2 | Connection 后无模型 | 补齐 `GET /v1/models` 端点 |
| T3 | 401 API Key | 修复 compose `env_file` 覆盖顺序 |
| T4 | 上游连接错误 | 将 `litellm-claude-code` 纳入 compose 并联通 |
| T5 | LiteLLM 重启循环 | 修正 key 规范与认证挂载方式 |
| T6 | Step 3 报无 echo / 工具语境异常 | A/B 排查上游语境影响 |
| T7 | Anthropic 路径 404/参数不一致 | 修正模型路由策略，不强改无前缀模型名 |
| T8 | `UnsupportedParamsError` | 流式收尾请求补传 `tools/tool_choice` |
| T9 | Step 3 复测通过 | Thinking/Running 可见，返回 `hello tool loop` |
| T10 | subscription 回归（经 `claude-max-proxy`） | 工具边界正确，Step 3 再次通过 |
| T11 | Step2/Step4 回归 | Step2 通过；Step4 通过但发现 `<system-reminder>` 文本泄露 |

## 6. 当前状态与下一步

- 当前状态:
  - Epic 1 的 Step 1/2/3/4/5 已通过。
  - Tool Loop 核心链路已跑通并有日志证据。
  - 存在一项非阻塞风险：偶发 `<system-reminder>` 文本泄露到用户可见回复。
- 下一步建议:
  - 增加输出清洗（过滤 `<system-reminder>` 片段）并回归验证。
  - 回到性能专项：在 Step 3 稳定前提下重新测 TTFB，并记录基线与优化后数据。
