# 双路径架构迁移实施指南

日期: 2026-02-20
关联文档: [dual-path-architecture-migration-assesment.md](dual-path-architecture-migration-assesment.md)

## 执行模式说明

每个步骤标注执行者：

| 标记 | 含义 |
|------|------|
| `[Agent]` | Claude 自动执行（文件编辑、命令运行、文档更新） |
| `[Human]` | 需要人类操作（GUI 交互、宿主机资源准备） |
| `[Agent → Human 确认]` | Claude 执行后需人类验证结果 |

**门控规则：逐步执行，每完成一个步骤后报告结果并等待用户确认，再进入下一步。禁止跨步骤批量执行。**

## 1. 实施步骤（可执行清单）

### 步骤 0：准备与基线确认 `[Agent]`

- 操作:
  - 确认当前分支状态可控。
  - 确认目标基线链路：`Open WebUI -> agent-service -> claude-max-proxy`。
- 命令:
  ```bash
  git status --short
  docker compose -f mentor-agent-service/docker-compose.yml ps
  ```
- 通过标准:
  - 工作区状态清晰。
  - 核心服务状态可见。

### 步骤 1：claude-max-proxy 容器化与 docker-compose 更新 `[Agent → Human 确认]`

> **前置条件：** claude-max-proxy 当前以宿主机进程运行（`host.docker.internal:3456`）。本步骤将其纳入 docker-compose 统一编排。

- `[Human]` 确认宿主机 `~/.claude-max-proxy.json` token 文件存在且包含 refreshToken：
  ```bash
  cat ~/.claude-max-proxy.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('refreshToken') else 'MISSING refreshToken')"
  ```
- `[Agent]` 操作:
  1. 在 `claude-max-proxy/` 目录创建 Dockerfile：
     ```dockerfile
     FROM node:20-slim
     WORKDIR /app
     COPY package.json server.js ./
     EXPOSE 3456
     CMD ["node", "server.js"]
     ```
  2. 更新 `mentor-agent-service/docker-compose.yml`：
     - 新增 `claude-max-proxy` 服务（基线上游）。
     - `litellm-claude-code` 服务标注为 `[Non-baseline]`，移入 `profiles: [fallback]` 使其可选启动。
     - `agent-service` 的 `depends_on` 改为 `claude-max-proxy`。
     ```yaml
     claude-max-proxy:
       container_name: claude-max-proxy
       build: ../claude-max-proxy
       ports:
         - "3456:3456"
       volumes:
         - ${CLAUDE_TOKENS_PATH:-~/.claude-max-proxy.json}:/root/.claude-max-proxy.json
       restart: unless-stopped

     # [Non-baseline] Claude subscription CLI wrapper — 工具调用受限，仅作可选路径
     litellm-claude-code:
       profiles: [fallback]
       # ... 原有配置保持不变
     ```
     > **为什么挂载文件而非 `CLAUDE_ACCESS_TOKEN` 环境变量？** `CLAUDE_ACCESS_TOKEN` 仅适合临时验证；生产/长期运行建议挂载 `~/.claude-max-proxy.json`（含 accessToken / refreshToken / expiresAt），proxy 会在 token 过期前自动刷新，降低中断风险。
  3. `agent-service` 依赖更新：
     ```yaml
     agent-service:
       depends_on:
         - claude-max-proxy
     ```
- 验证命令:
  ```bash
  docker compose -f mentor-agent-service/docker-compose.yml build claude-max-proxy
  docker compose -f mentor-agent-service/docker-compose.yml up -d claude-max-proxy
  curl -sS http://127.0.0.1:3456/health
  ```
- 通过标准:
  - `claude-max-proxy` 容器正常启动。
  - `/health` 返回成功。
  - `litellm-claude-code` 不会默认启动（需 `--profile fallback` 手动拉起）。

### 步骤 2：配置 subscription baseline `[Agent]`

- 操作:
  1. 编辑 `mentor-agent-service/.env`：
     ```env
     LITELLM_BASE_URL=http://claude-max-proxy:3456/v1
     LITELLM_KEY=sk-dev-key          # 占位值；claude-max-proxy 不校验此 key，实际认证走 OAuth token 文件
     LITELLM_MODEL=openai/claude-sonnet-4-6
     ```
  2. 更新 `mentor-agent-service/.env.example`，提供双 profile 配置示例：
     ```env
     # --- Subscription Profile (Baseline) ---
     LITELLM_BASE_URL=http://claude-max-proxy:3456/v1
     LITELLM_KEY=sk-dev-key          # 占位值，claude-max-proxy 不校验；仅 API profile 需要真实 key
     LITELLM_MODEL=openai/claude-sonnet-4-6

     # --- API Profile (Fallback, uncomment to switch) ---
     # LITELLM_BASE_URL=https://api.anthropic.com
     # LITELLM_KEY=sk-ant-xxx
     # LITELLM_MODEL=anthropic/claude-sonnet-4-6
     ```
- 验证命令:
  ```bash
  docker exec -it mentor-agent-service sh -lc "printenv | grep -E 'LITELLM_BASE_URL|LITELLM_MODEL'"
  ```
- 通过标准:
  - 环境变量与预期一致。

### 步骤 3：重启并校验 agent-service `[Agent]`

- 操作:
  - 重建并重启 `agent-service`。
- 命令:
  ```bash
  docker compose -f mentor-agent-service/docker-compose.yml up -d --build --force-recreate agent-service
  curl -sS http://127.0.0.1:8100/v1/models -H "Authorization: Bearer dev-token"
  ```
- 通过标准:
  - `/v1/models` 返回 200。
  - 模型包含 `openai/claude-sonnet-4-6`。

### 步骤 4：连接校验 `[Agent → Human 确认]`

- `[Agent]` API 级验证:
  ```bash
  curl -sS http://127.0.0.1:8100/v1/chat/completions \
    -H "Authorization: Bearer dev-token" \
    -H "Content-Type: application/json" \
    -d '{"model":"openai/claude-sonnet-4-6","messages":[{"role":"user","content":"请直接回复当前可用工具名称列表（仅名称）"}]}'
  ```
- 通过标准:
  - 响应包含 `echo / search_knowledge_base / list_knowledge_bases`。
- `[Human]` Open WebUI GUI 验证:
  - Open WebUI 保持连接 `http://agent-service:8100/v1`（禁止直连上游代理）。
  - 新建会话并选择 `openai/claude-sonnet-4-6`。
  - 发送：`用 echo 工具返回 hello tool loop`
  - 通过标准：可见 `Thinking/Running`，最终返回 `hello tool loop`。

### 步骤 5：记录与文档联动 `[Agent]`

- 操作:
  1. 回填测试结果到 `docs/epic1-user-testing-report.md`。
  2. 按评估报告 Section 6 的变更清单，更新以下高影响设计文档：
     - `_bmad-output/planning-artifacts/architecture.md` — 硬约束改为双路径、新增术语表与基线声明
     - `_bmad-output/implementation-artifacts/1-2-openai-compatible-api-basic-llm-proxy.md` — 上游模式改为路径无关描述
     - `_bmad-output/implementation-artifacts/1-3-tool-use-loop-engine.md` — 区分两条路径的工具调用机制
  3. 为所有受影响文档添加元信息头：
     ```markdown
     Status: [Active | Proposed | Deprecated]
     Baseline Profile: subscription (claude-max-proxy)
     Last validated: YYYY-MM-DD
     ```
- 建议命令:
  ```bash
  docker compose -f mentor-agent-service/docker-compose.yml logs --tail 200 agent-service
  ```
- 通过标准:
  - 结果可复现、可追溯。
  - 高影响文档已更新且包含元信息头。

## 2. 回滚步骤（5 分钟恢复）

### 触发条件

- 出现外部工具语境污染。
- 步骤 4（连接校验）连续失败（>= 2 次）。
- subscription 上游持续 `Not Found` 或 `5xx`。

### 回滚到 API profile

- 操作:
  - 编辑 `mentor-agent-service/.env`：
    ```env
    LITELLM_BASE_URL=https://api.anthropic.com
    LITELLM_KEY=sk-ant-xxx
    LITELLM_MODEL=anthropic/claude-sonnet-4-6
    ```
  - 重启 `agent-service`。
- 命令:
  ```bash
  docker compose -f mentor-agent-service/docker-compose.yml up -d --force-recreate agent-service
  curl -sS http://127.0.0.1:8100/v1/models -H "Authorization: Bearer dev-token"
  ```
- 回滚成功标准:
  - `/v1/models` 恢复为 API profile 模型。
  - 步骤 4 验证用例恢复通过。

### 回滚记录模板

- 触发原因:
- 执行人:
- 时间:
- 执行命令:
- 验证结果:

## 3. 完成定义（DoD）

- 架构与文档
  - [ ] 基线路径声明已更新且与实际一致。
  - [ ] 非基线路径有明确免责声明（标注 `[Non-baseline]`）。
  - [ ] 受影响文档顶部有元信息头（Status / Baseline Profile / Last validated）。
- 基础设施
  - [ ] `claude-max-proxy` 已容器化，纳入 docker-compose 编排。
  - [ ] `agent-service` 通过 Docker 内部网络 `http://claude-max-proxy:3456` 访问基线上游（不依赖 `host.docker.internal`）。
  - [ ] `litellm-claude-code` 标注为非基线，不默认启动。
  - [ ] `.env.example` 提供双 profile 配置示例（subscription 为默认值）。
- 功能验收（Epic 1 验证步骤 1-5，基线路径下执行）
  - [ ] Epic 1 验证步骤 1-5 在基线路径下全部通过。
  - [ ] subscription profile：`echo` 工具连续 20 次调用，成功率 >= 90%。
  - [ ] subscription profile：`search_knowledge_base` 连续 10 次调用，成功率 >= 85%。
  - [ ] profile 切换：修改 `.env` 后重启，两条路径均可正常工作。
- 运维与恢复
  - [ ] API profile 回滚演练成功至少 1 次。
  - [ ] 回滚记录完整可审计。
