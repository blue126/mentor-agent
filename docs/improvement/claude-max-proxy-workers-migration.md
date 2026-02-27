# ~~claude-max-proxy Cloudflare Workers 移植方案~~ (DEPRECATED)

**状态**: **DEPRECATED** — claude-max-proxy 已合并为 unified-proxy（支持 Anthropic + OpenAI 双 OAuth）。如需 Workers 移植，需基于 unified-proxy 新架构重新评估。
**优先级**: ~~Low~~
**估算工作量**: ~~1-2 天~~
**日期**: 2026-02-25

---

## 背景与动机

### 现状

`claude-max-proxy` 是一个单文件 Node.js 应用（`server.js`），负责将 OpenAI-compatible 格式的请求转换并代理至 Anthropic Claude API，同时管理 OAuth token 的本地持久化与刷新。当前部署方式为本地进程或 Docker 容器，绑定在开发机或内网服务器上。

### 参照先例

兄弟项目 `codex-proxy`（dvcrn/codex-proxy，Go 实现）已经通过 WebAssembly 成功部署至 Cloudflare Workers，验证了"将此类 OAuth 代理运行在 Workers 边缘环境"的可行性。其 `cmd/claude-code-proxy-worker/main.go` 与 `internal/credentials/cloudflare_kv.go` 可作为直接参考。

### 移植收益

| 收益 | 说明 |
|------|------|
| 全球边缘部署 | 就近接入，降低延迟 |
| 零服务器运维 | 无需维护 Docker / VPS |
| 免费额度 | Free tier 100,000 req/day，足够个人使用 |
| DDoS 防护 | Cloudflare 网络层自动防护 |
| 高可用 | Workers 平台 SLA，无单点故障 |

---

## 现有架构分析

### Node.js API 兼容性评估

| 当前使用的 API / 模块 | Workers 兼容性 | 说明 |
|----------------------|---------------|------|
| `fetch()` | 兼容 | Workers 原生支持 |
| `JSON.parse` / `JSON.stringify` | 兼容 | 标准 JS，无需改动 |
| SSE streaming（`res.write`） | 需适配 | 改用 `TransformStream` + `ReadableStream` |
| `node:crypto` (`randomUUID` 等) | 兼容 | Workers 提供 `crypto.randomUUID()` |
| `node:http` `createServer` | 需替换 | 改为 `export default { fetch(request, env) {} }` |
| `node:fs` 读写 `auth.json` | 需替换 | 改用 Cloudflare KV 存储 token |
| `execSync("security find-generic-password...")` Keychain | 不兼容 | 改为 admin API 注入凭证 |
| `node:readline` `--login` 交互 | 不兼容 | 改为 Web-based OAuth callback flow |

**结论**：核心代理逻辑（消息格式转换、SSE 流式转发、XML tool call 解析）全部基于标准 `fetch()`，**无需改动**。主要工作集中在 I/O 层适配，即入口、存储、认证三个模块。

---

## 改造方案

### 1. 入口层适配（HTTP Server → Workers Fetch Handler）

**当前（Node.js）：**

```js
import http from 'node:http';

const server = http.createServer((req, res) => {
  // route handling
});
server.listen(PORT);
```

**目标（Workers）：**

```js
export default {
  async fetch(request, env, ctx) {
    return handleRequest(request, env);
  }
};
```

路由逻辑保持不变，仅将 `req`/`res` 替换为标准 `Request`/`Response` 对象。Workers 的 `Request` API 与浏览器标准一致，迁移成本低。

---

### 2. 凭证存储迁移（`node:fs` → Cloudflare KV）

**当前实现**：将 OAuth token（`access_token`、`refresh_token`、`expires_at`）序列化为 JSON 写入本地 `auth.json` 文件。

**目标实现**：使用 Cloudflare KV Namespace 替代文件存储。

```js
// KV key 设计
const KV_KEY_TOKEN = 'claude_oauth_token';

// 读取 token
async function loadToken(env) {
  const raw = await env.AUTH_KV.get(KV_KEY_TOKEN);
  return raw ? JSON.parse(raw) : null;
}

// 写入 token
async function saveToken(env, tokenData) {
  await env.AUTH_KV.put(KV_KEY_TOKEN, JSON.stringify(tokenData), {
    expirationTtl: tokenData.expires_in ?? 86400
  });
}
```

**Admin API 端点**（用于初始凭证注入与状态查询）：

| Method | Path | 说明 |
|--------|------|------|
| `POST` | `/admin/credentials` | 注入或更新 OAuth token（需 `ADMIN_SECRET` 鉴权） |
| `GET` | `/admin/credentials/status` | 查询当前 token 有效期与状态 |
| `DELETE` | `/admin/credentials` | 撤销并清除存储的 token |

`ADMIN_SECRET` 通过 Workers Secret（`wrangler secret put ADMIN_SECRET`）注入，不写入代码。

---

### 3. OAuth 登录流程改造（CLI `--login` → Web Callback）

**当前实现**：通过 `node:readline` 在终端交互，调用 `execSync("security...")` 从 macOS Keychain 读取初始 token。

**目标实现**：实现标准 OAuth 2.0 Authorization Code Flow，在 Workers 上暴露 callback 端点。

```
用户浏览器
  │
  ├─ GET /oauth/start
  │     → 重定向至 Anthropic OAuth 授权页
  │
  ├─ Anthropic 授权后回调
  │     → GET /oauth/callback?code=xxx
  │         → 用 code 换取 access_token + refresh_token
  │         → 写入 KV 存储
  │         → 返回成功页面
  │
  └─ 后续请求直接使用 KV 中的 token，自动刷新
```

OAuth state 参数存入 KV（TTL 5 分钟）防止 CSRF。

---

### 4. SSE 流式响应适配（`res.write` → `TransformStream`）

**当前实现**：直接调用 `res.write(chunk)` 逐块写入 HTTP 响应。

**目标实现**：使用 `TransformStream` 构造 `ReadableStream`，Workers 原生支持流式响应。

```js
function createSSEStream(upstreamResponse) {
  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();
  const reader = upstreamResponse.body.getReader();

  (async () => {
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        await writer.write(value);
      }
    } finally {
      await writer.close();
    }
  })();

  return new Response(readable, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Transfer-Encoding': 'chunked',
    }
  });
}
```

核心 SSE 解析与 XML tool call 处理逻辑**零改动**，只是改变了数据写出的方式。

---

### 5. 双模式架构（本地 Node.js + Workers 同源码）

为避免维护两套代码，推荐采用**构建时条件分支**策略，通过环境变量或构建标志区分运行环境。

**目录结构建议：**

```
claude-max-proxy/
├── src/
│   ├── core/
│   │   ├── proxy.js          # 核心代理逻辑（零平台依赖，共用）
│   │   ├── message-convert.js
│   │   └── tool-call-parser.js
│   ├── adapters/
│   │   ├── node-storage.js   # fs-based token 存储
│   │   ├── kv-storage.js     # KV-based token 存储
│   │   ├── node-server.js    # node:http 入口
│   │   └── workers-entry.js  # Workers fetch handler 入口
│   └── auth/
│       ├── oauth-cli.js      # CLI --login 流程
│       └── oauth-web.js      # Web callback 流程
├── wrangler.toml             # Workers 配置
└── server.js                 # 现有 Node.js 入口（保持不变）
```

**运行时判断（可选，无需构建工具）：**

```js
// workers-entry.js
import { createProxyHandler } from './core/proxy.js';
import { KVStorage } from './adapters/kv-storage.js';

export default {
  async fetch(request, env) {
    const storage = new KVStorage(env.AUTH_KV);
    return createProxyHandler(storage)(request, env);
  }
};
```

---

## 工作量估算

| 模块 | 工作内容 | 估算时间 |
|------|----------|----------|
| 入口层适配 | `http.createServer` → Workers fetch handler | 2 小时 |
| KV 存储适配 | 实现 `kv-storage.js`，替换 `node:fs` 调用 | 3 小时 |
| Admin API | 凭证注入端点 + ADMIN_SECRET 鉴权 | 2 小时 |
| Web OAuth callback | `/oauth/start` + `/oauth/callback` 实现 | 4 小时 |
| SSE 流式适配 | `TransformStream` 封装 | 2 小时 |
| 代码拆分重构 | 抽取 `core/` 层，建立双模式结构 | 3 小时 |
| `wrangler.toml` 配置 | KV binding、Secret、Routes 配置 | 1 小时 |
| 测试与验证 | 本地 `wrangler dev` 测试 + 端到端验证 | 3 小时 |
| **合计** | | **约 1.5-2 天** |

**核心代理逻辑（消息格式转换、SSE 解析、XML tool call 解析）：零改动。**

---

## 风险与局限

| 风险 | 级别 | 说明 | 缓解措施 |
|------|------|------|----------|
| Workers CPU time 限制 | 中 | Free tier: 10ms CPU/req；Paid: 30s。长 streaming 响应可能超限 | 使用 Paid plan（$5/月）；流式转发本身 CPU 消耗极低，实测风险不大 |
| 凭证注入不如 Keychain 便捷 | 低 | 需手动调用 admin API 注入 token，不能自动从 macOS Keychain 读取 | 提供脚本封装 `inject-token.sh` |
| 调试难度增加 | 低 | Workers 日志通过 `wrangler tail` 查看，不如本地 `console.log` 直观 | 本地用 `wrangler dev` 模拟，保留 Node.js 模式作为开发环境 |
| Token 自动刷新时序 | 中 | 并发请求可能同时触发 refresh，需要 KV 层加锁或幂等处理 | 使用 KV 的 `put` with TTL + 请求级别的刷新锁 |
| Workers 冷启动 | 低 | 首次请求有轻微延迟（~10ms），对代理场景影响极小 | 无需处理，可接受 |

---

## 优先级与依赖

**优先级**: Low（Nice-to-have，不影响当前核心功能）

**当前阻塞情况**: 无。本地 Docker 部署完全可用，Workers 移植为可选增强。

**可并行执行**: 与其他 Story 无强依赖，可独立开发。

**软依赖**:

- Story 1-7（providers.yaml 多 provider 配置）完成后，Workers 版本可直接复用 provider 路由逻辑，建议在该 Story 完成后再启动此改进。

---

## 参考资料

| 资源 | 说明 |
|------|------|
| `codex-proxy` `cmd/claude-code-proxy-worker/main.go` | Workers 入口层实现参考 |
| `codex-proxy` `internal/credentials/cloudflare_kv.go` | KV 凭证存储实现参考 |
| [Cloudflare Workers 官方文档](https://developers.cloudflare.com/workers/) | Workers Runtime API 参考 |
| [Cloudflare KV 文档](https://developers.cloudflare.com/kv/) | KV Namespace 使用说明 |
| [wrangler CLI 文档](https://developers.cloudflare.com/workers/wrangler/) | 部署工具文档 |
| Cloudflare Workers Free Tier 限制 | 100k req/day，10ms CPU/req，无 Durable Objects |
