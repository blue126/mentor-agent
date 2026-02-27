# 统一订阅代理：合并 claude-max-proxy + codex-proxy

**状态**: **Implemented** (已实施，2026-02-26)
**优先级**: ~~High~~
**预估工作量**: ~~0.5 天~~
**结果**: unified-proxy 已替代 claude-max-proxy + codex-proxy，支持 Anthropic OAuth + OpenAI ChatGPT Backend OAuth。ChatGPT Backend 格式转换逻辑从 codex-proxy (Go) 移植到 unified-proxy (Node.js)。codex-proxy 目录已删除。

---

## 背景与动机

### 当前架构

```
agent-service → claude-max-proxy (Node.js, 容器1) → api.anthropic.com
agent-service → codex-proxy     (Go,      容器2) → chatgpt-api
```

两个独立的 proxy 进程/容器，分别处理 Anthropic 和 OpenAI 的订阅 OAuth 认证。

### 问题

1. **运维复杂度**: 3 个容器（app + 2 proxy），两套凭据管理，两套 Docker volume 挂载
2. **代码重复**: 两个 proxy 的核心逻辑几乎相同 — OAuth token 管理 + OpenAI-compatible API + SSE streaming 转发
3. **语言分裂**: claude-max-proxy (Node.js) vs codex-proxy (Go)，维护成本高
4. **Token 冲突风险**: codex-proxy 依赖 CLI 凭据迁移（`--creds-store=auto`），与 Codex CLI 共享 `refresh_token`，存在 racing condition

### 目标架构

```
agent-service → unified-proxy (Node.js, 容器1) → api.anthropic.com
                                                → api.openai.com
```

在 claude-max-proxy 基础上扩展，增加 OpenAI 订阅 OAuth 支持，合并为单一容器。

---

## 可行性分析

### 已有基础（claude-max-proxy）

| 能力 | 现状 | 备注 |
|---|---|---|
| Anthropic OAuth PKCE login | `--login` CLI 模式 | 完整实现 |
| Token refresh + 后台续期 | `doRefreshToken()` + `setInterval` | 完整实现 |
| Credential 文件读写 | `AUTH_FILE`，`saveTokensToFile()` | 完整实现 |
| OpenAI-compatible API server | `/v1/chat/completions`、`/v1/models` | 完整实现 |
| SSE streaming proxy | Anthropic SSE → OpenAI SSE 格式转换 | 完整实现 |
| Tool calling (XML bridge) | `parseXmlToolCalls()`、`toolCallsToXml()` | Anthropic 专用 |

### 新增工作

| 项 | 工作量 | 说明 |
|---|---|---|
| OpenAI OAuth 参数配置 | 0.5h | client_id、endpoints 已确认（见下方） |
| OpenAI PKCE login (`--login openai`) | 1h | 复用现有 Anthropic login 逻辑，换参数 |
| OpenAI token refresh | 0.5h | 复用 `doRefreshToken()` 结构 |
| Model → provider 路由 | 1h | `gpt-*` → OpenAI endpoint，`claude-*` → Anthropic endpoint |
| 单一 auth.json 双 section | 0.5h | `auth.json` 内含 `anthropic` + `openai` section |
| **合计** | **~3.5h** | |

---

## OpenAI OAuth 参数（已确认）

以下参数已从多个独立来源交叉验证（openai/codex 官方 CLI、open-hax/codex TypeScript 实现、codex-proxy 源码）：

| 参数 | 值 |
|---|---|
| Client ID | `app_EMoamEEZ73f0CkXaXp7hrann` |
| Authorization Endpoint | `https://auth.openai.com/oauth/authorize` |
| Token Endpoint | `https://auth.openai.com/oauth/token` |
| Redirect URI | `http://localhost:1455/auth/callback` |
| Scope (授权时) | `openid profile email offline_access` |
| Scope (刷新时) | `openid profile email` |
| PKCE Method | `S256` |

### 与 Anthropic OAuth 的对比

| 项 | Anthropic | OpenAI |
|---|---|---|
| Client ID | `9d1c250a-e61b-44d9-88ed-5944d1962f5e` | `app_EMoamEEZ73f0CkXaXp7hrann` |
| Auth URL | `https://claude.ai/oauth/authorize` | `https://auth.openai.com/oauth/authorize` |
| Token URL | `https://console.anthropic.com/v1/oauth/token` | `https://auth.openai.com/oauth/token` |
| Login 方式 | 浏览器授权 → 粘贴 code | 浏览器授权 → localhost callback |
| API Endpoint | `https://api.anthropic.com/v1/messages` | `https://api.openai.com/v1/chat/completions` |

---

## 设计要点

### 1. 路由策略

```javascript
function routeRequest(model) {
  if (model.startsWith('gpt-') || model.startsWith('o1') || model.startsWith('o3') || model.startsWith('o4')) {
    return 'openai';
  }
  return 'anthropic';  // 默认
}
```

### 2. 凭据隔离

```
~/.unified-proxy/
  └── auth.json             # 单一文件，anthropic + openai 双 section
```

单一 `auth.json` 内含 `anthropic` 和 `openai` 两个顶层 section，两个 provider 的 `refresh_token` chain 完全独立，互不干扰。

### 3. 请求转发

- **Anthropic**: 维持现有逻辑（OpenAI → Anthropic 格式转换 + SSE 转换）
- **OpenAI**: 直接转发 Chat Completions 请求（格式天然兼容），仅需注入 OAuth Bearer token

OpenAI 侧不需要格式转换 — LiteLLM 发出的就是 OpenAI Chat Completions 格式，直接加上 `Authorization: Bearer <token>` 转发即可。

### 4. Login 命令

```bash
# Anthropic 登录（现有）
node server.js --login

# OpenAI 登录（新增）
node server.js --login openai

# 或同时登录两个
node server.js --login all
```

### 5. 模型适配

GPT-5.2 使用标准 Chat Completions API，**不需要**：
- Responses API → Chat Completions 转换
- WebSocket 连接
- 特殊的 SSE 格式转换

---

## 改造后的 docker-compose

```yaml
# 统一订阅代理 — 同时支持 Anthropic + OpenAI
unified-proxy:
  container_name: unified-proxy
  build: ../unified-proxy  # 或继续用 ../claude-max-proxy
  ports:
    - "3456:3456"
  volumes:
    - ${PROXY_AUTH_DIR:-~/.unified-proxy}:/data:rw
    - ${CLAUDE_CLI_AUTH_DIR:-~/.claude}:/root/.claude:ro  # Anthropic CLI fallback
  environment:
    - HOST=0.0.0.0
    - AUTH_FILE=/data/auth.json  # 单一文件，含 anthropic + openai 双 section
  restart: unless-stopped
```

从 3 容器减为 2 容器（agent-service + unified-proxy + open-webui）。

---

## 手动 OAuth 重新认证方式

当 Docker 停机时间超过 `refresh_token` 有效期（通常 30 天），token 会完全过期，需要手动重新认证。

### 当前方式（改造前）

| Proxy | 重新认证命令 | 步骤数 | 说明 |
|---|---|---|---|
| **claude-max-proxy** | `node server.js --login` | 1 步 | 浏览器打开 → 登录 → 粘贴 code → 完成 |
| **codex-proxy** | 先 `codex login`，再重启容器（`--creds-store=auto` 迁移） | 2 步 | 依赖 Codex CLI 先登录；迁移会触发 refresh_token racing condition |

**codex-proxy 的问题**: 依赖 CLI 凭据迁移，每次迁移都复制 CLI 的 `refresh_token`，一旦 proxy 刷新了 token，CLI 的 `refresh_token` 就失效了（同一 `client_id` 的 rotation 机制）。

### 改造后方式

| Provider | 重新认证命令 | 步骤数 | 说明 |
|---|---|---|---|
| **Anthropic** | `node server.js --login` | 1 步 | 浏览器授权 → 粘贴 code → 保存独立 token |
| **OpenAI** | `node server.js --login openai` | 1 步 | 浏览器授权 → localhost callback → 保存独立 token |
| **两个一起** | `node server.js --login all` | 1 步 | 依次完成两个 provider 的授权 |

**改进**: OpenAI 侧获得独立的 `refresh_token`，不再与 Codex CLI 共享，彻底消除 racing condition。

### Token 生命周期速查

| 阶段 | Anthropic | OpenAI |
|---|---|---|
| access_token 有效期 | ~1 小时 | ~1 小时 |
| refresh_token 有效期 | ~30 天 | ~30 天 |
| 后台自动续期 | 每 30 分钟检查，提前 2 小时刷新 | 同上（复用相同逻辑） |
| 需手动重新认证 | Docker 停机 > 30 天 | Docker 停机 > 30 天 |

---

## 风险评估

| 风险 | 等级 | 缓解措施 |
|---|---|---|
| OpenAI OAuth 参数变化 | 低 | 已从 3 个独立实现交叉验证 |
| Chat Completions API 格式差异 | 低 | GPT-5.2 使用标准格式，无需转换 |
| 项目更名带来的路径变更 | 低 | 可先保持 `claude-max-proxy` 目录名，后续再重命名 |
| OpenAI 订阅后端限流策略不同 | 中 | 需实测确认，可能需要加 retry 逻辑 |

---

## 参考实现

| 项目 | 语言 | OAuth 方式 | 备注 |
|---|---|---|---|
| openai/codex CLI | Rust | Browser PKCE → localhost callback | 官方实现，参数来源 |
| open-hax/codex | TypeScript | 同上 | 开源分支，参数确认 |
| codex-proxy | Go | CLI token 迁移 | 当前方案（有 racing condition） |
| opencode | TypeScript | Custom fetch interceptor | 无 proxy 方案（仅 TypeScript 生态适用） |
| claude-max-proxy | Node.js | Browser PKCE → 粘贴 code | 我们的 Anthropic 侧实现 |
