# Plan: 移植 ChatGPT Backend 转换逻辑到 unified-proxy

## Context

unified-proxy 的 OpenAI handler 当前直接调用 `https://api.openai.com/v1/chat/completions`（Platform API，按 API credits 计费），但我们的 OAuth token 来自 ChatGPT 订阅，只能通过 `https://chatgpt.com/backend-api/codex/responses`（ChatGPT Backend，按订阅计费）使用。

codex-proxy（Go）已实现完整的格式转换逻辑。本计划将核心转换逻辑移植到 unified-proxy（Node.js），使 GPT-5.2 通过订阅计费正常工作。

## 修改文件

**唯一文件**: `unified-proxy/server.js`

## 变更概要

### 1. 常量更新

保留原常量作为回滚路径，新增 ChatGPT Backend URL：

```javascript
const OPENAI_PLATFORM_API_URL = 'https://api.openai.com/v1/chat/completions';  // 保留，未来 API credits 可用
const OPENAI_CHATGPT_BACKEND_URL = 'https://chatgpt.com/backend-api/codex/responses';  // 订阅计费
```

`handleOpenAIChat` 中使用 `OPENAI_CHATGPT_BACKEND_URL`。

### 2. OAuth 登录与 refresh：存储并保留 account_id

**登录时**：`loginOpenAI()` 中，OAuth token 响应包含 `id_token`（JWT）。解析其 `sub` claim 作为 `accountId`，一并存入 auth.json 的 openai section：

```json
{ "openai": { "accessToken": "...", "refreshToken": "...", "expiresAt": ..., "accountId": "..." } }
```

JWT 解析：base64url decode payload 部分，无需外部依赖。

**Refresh 时**：`doRefreshToken()` 和 `saveTokensForProvider()` 需要 merge 逻辑——refresh 响应不含 `accountId`，必须从旧数据中保留：

```javascript
// doRefreshToken 返回时不包含 accountId
// saveTokensForProvider 改为 merge 而非覆盖：
function saveTokensForProvider(tokens, provider) {
  const data = loadAuthFile();
  data[provider] = { ...data[provider], ...tokens };  // merge，保留 accountId
  saveAuthFile(data);
}
```

缺少 `accountId` 时（旧 token 文件）：`getOAuthTokens('openai')` 返回后，`handleOpenAIChat` 检查 `tokens.accountId`，缺失则返回 503 + 提示重新 `--login openai`。

参考: codex-proxy `internal/credentials/fs.go` 中 `account_id` 的存储方式。

### 3. 请求转换：Chat Completions → Codex Responses

新增 `convertToCodexRequest(body)` 函数，将 OpenAI Chat Completions 请求体转换为 Codex Responses 格式。

**消息映射**：

| Chat Completions | Codex Responses |
|---|---|
| `messages[role=system].content` | `instructions` |
| `messages[role=user].content` | `input[]: { type: "message", role: "user", content: [{ type: "input_text", text }] }` |
| `messages[role=assistant].content` | `input[]: { type: "message", role: "assistant", content: [{ type: "output_text", text }] }` |
| `messages[role=assistant].tool_calls` | `input[]: { type: "function_call", name, call_id, arguments }` |
| `messages[role=tool]` | `input[]: { type: "function_call_output", call_id, output }` |

**采样/长度参数映射**：

| Chat Completions | Codex Responses |
|---|---|
| `max_tokens` | `max_output_tokens`（Responses API 字段名） |
| `temperature` | `temperature`（透传） |
| `top_p` | `top_p`（透传） |
| `stop` | 返回 400 `unsupported_parameter`（Responses API 不支持 stop sequences，显式拒绝避免调用方误以为生效） |
| `n` | 返回 400 `unsupported_parameter`（Responses API 不支持多 choices） |

**Tools 映射**：

| Chat Completions | Codex Responses |
|---|---|
| `tools[].function` | `tools[]: { type: "function", name, description, strict: false, parameters }` |
| `tool_choice`（string 或 object） | `tool_choice`（normalize：string 透传；`{ type: "function", function: { name } }` → `{ type: "function", name }`） |

**固定字段**：`store: false`, `stream: true`, `model`（stripPrefix 后直传）。

**Scope 限制**：仅支持文本 + tools。不支持多模态输入（image_url 等），遇到时返回 400 `unsupported_content_type`（静默丢弃内容会导致语义偏差，排障困难）。

**不需要移植**（codex-proxy 特有）：
- `inversePrompt` / `replaceNames`（Codex CLI 身份伪装）
- reasoning effort clamping
- `prompt_cache_key`
- WebSocket transport

参考: codex-proxy `internal/server/transform.go` 第 158-213 行 `buildCodexRequestBody()`、第 558-650 行 `buildCodexInputMessages()`、第 727-757 行 `mapToolsToCodex()`。

### 4. Headers

最小必要集，UA/version 提取为常量便于后续更新：

```javascript
const CODEX_CLI_VERSION = '0.104.0';
const CODEX_CLI_UA = `codex_cli_rs/${CODEX_CLI_VERSION}`;

// 请求头
{
  'authorization': `Bearer ${tokens.accessToken}`,
  'content-type': 'application/json',
  'accept': 'text/event-stream',
  'chatgpt-account-id': tokens.accountId,
  'openai-beta': 'responses=experimental',
  'originator': 'codex_cli_rs',
  'user-agent': CODEX_CLI_UA,
  'version': CODEX_CLI_VERSION,
}
```

参考: codex-proxy `internal/server/server.go` 第 451-463 行。

### 5. 响应 SSE 转换：Codex Responses → Chat Completions

新增 `CodexSSETransformer` class，处理 ChatGPT Backend 返回的 SSE 事件：

| Codex 事件 | Chat Completions 输出 |
|---|---|
| `response.created` | 记录 responseID；发送首个 chunk `{ delta: { role: "assistant" } }`（部分 OpenAI 兼容客户端依赖此字段） |
| `response.output_text.delta` | `{ delta: { content }, finish_reason: null }` |
| `response.output_item.added` (function_call) | `{ delta: { tool_calls: [{ index, id, type, function: { name, arguments: "" } }] } }` |
| `response.function_call_arguments.delta` | `{ delta: { tool_calls: [{ index, function: { arguments: delta } }] } }` |
| `response.completed` | `{ delta: {}, finish_reason }` + `usage` 对象 |
| SSE error 事件 / 非 200 状态 | 转发为标准 OpenAI error JSON |
| 其他事件 | 忽略 |

**finish_reason 映射**（从 `response.completed` 中的 `response.status` 或推断）：

| 条件 | finish_reason |
|---|---|
| 正常结束，无 tool calls | `"stop"` |
| 正常结束，有 tool calls | `"tool_calls"` |
| upstream `response.incomplete` 或 `max_output_tokens` 触发 | `"length"` |
| upstream 连接中断 / 异常 | `"stop"` + error log |

**usage 提取**：从 `response.completed` 事件中的 `response.usage` 映射：
- `input_tokens` → `prompt_tokens`
- `output_tokens` → `completion_tokens`
- 计算 `total_tokens`
- 缺失时返回 `{ prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 }`

参考: codex-proxy `internal/server/transform.go` 第 761-1120 行 `SSETransformer.Transform()`。

### 6. handleOpenAIChat 重写

替换当前的直通逻辑：

```
Before: body → api.openai.com/v1/chat/completions → pipe response
After:  body → convertToCodexRequest() → chatgpt.com/backend-api/codex/responses → CodexSSETransformer → Chat Completions SSE
```

**错误处理**：
- upstream 非 200：读取 body，log 错误，返回标准 OpenAI error JSON（映射 status code）
- upstream 401：触发 token refresh + 重试一次（参考现有 Anthropic 逻辑）
- `accountId` 缺失：返回 503 + 提示 `--login openai`
- 连接超时：使用现有 `CONNECT_TIMEOUT_MS`

**Streaming 模式**：
- streaming 请求：逐 chunk 经 `CodexSSETransformer` 转换后发送给客户端
- non-streaming 请求：buffer 所有 chunks，聚合为 `{ id, object: "chat.completion", choices: [{ message, finish_reason }], usage }` JSON 响应。`id` 来源优先级：`response.created` 事件中的 upstream id（`chatcmpl-` + response.id） > 本地生成的 fallback id，保证可追踪性一致。

参考: codex-proxy `internal/server/server.go` 第 127-270 行、`internal/server/chat_completions_buffered.go`。

## 不修改的文件

- `providers.yaml` — 已正确配置 `gpt-5.2`
- `mentor-agent-service/` — 无需改动，LiteLLM 照常发 Chat Completions 格式
- auth.json 格式 — 向后兼容（新增 `accountId` 字段，旧 token 缺失时提示重新登录）

## 验证

### Smoke test 脚本（6 组 curl 回归用例）

```bash
PROXY=http://localhost:3456

# 1) sync 文本
curl -s -X POST $PROXY/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-5.2","messages":[{"role":"user","content":"Say hello"}]}'
# 期望: 200, choices[0].message.content 非空

# 2) stream 文本
curl -s -N -X POST $PROXY/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-5.2","messages":[{"role":"user","content":"Say hello"}],"stream":true}'
# 期望: SSE chunks，最终 data: [DONE]

# 3) tool call（含 arguments 分片）
curl -s -X POST $PROXY/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-5.2","messages":[{"role":"user","content":"What is the weather in Tokyo?"}],"tools":[{"type":"function","function":{"name":"get_weather","description":"Get weather","parameters":{"type":"object","properties":{"city":{"type":"string"}}}}}]}'
# 期望: choices[0].message.tool_calls 非空, finish_reason="tool_calls"

# 4) max_tokens 命中（期望 finish_reason=length）
curl -s -X POST $PROXY/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-5.2","messages":[{"role":"user","content":"Write a very long story about dragons"}],"max_tokens":5}'
# 期望: finish_reason="length"

# 5) 上游 401 → refresh → retry（模拟：写入明显非法 token 到 auth.json 的 openai.accessToken）
# 期望: proxy 检测到 401，触发 refresh（用有效 refreshToken），retry 成功返回 200
# 若 refreshToken 也失效: 503 + 错误信息包含 "login"

# 6) refresh 后仍可请求（验证 accountId 未丢）
# 步骤: 手动将 openai.expiresAt 设为过去时间 → 发请求 → 检查 refresh 成功且 accountId 保留
```

### 集成测试

在 Mac host 上：
1. `cd unified-proxy && node server.js --login openai`（重新登录以获取 accountId）
2. `docker compose up -d --build`
3. 在 Open WebUI 中选择 gpt-sub，发送消息，确认正常响应
4. 检查 `docker logs unified-proxy` 确认请求成功路由到 chatgpt.com
5. 三个 provider 完整验证：claude-sub、nvidia-nim、gpt-sub 都能正常对话
