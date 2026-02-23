# claude-max-proxy 独立 OAuth 认证改造方案

日期: 2026-02-22
状态: 已完成（2026-02-22 实施并验证通过）
关联 Issue: testing-report-epic2.md Issue #10

## 1. 背景与动机

### 当前问题

claude-max-proxy 依赖从宿主机 Claude Code CLI 导出的静态 token，存在三个致命缺陷：

1. **Refresh token 竞争**: OAuth refresh token 是一次性的（rotation 机制）。宿主机 CLI 刷新后，proxy 持有的副本在 Anthropic 服务端被作废
2. **client_id 过时**: proxy 硬编码的 `ce88c5c9-...` 已被 Anthropic 废弃，auto-refresh 从未成功
3. **macOS Keychain 不同步**: CLI 只更新 Keychain，不写回 `~/.claude/.credentials.json` 文件

### 对比：opencode 的方案

opencode 通过独立 OAuth 流程解决了同样的问题：
- 一次性浏览器授权，获取**专属** refresh_token
- 进程内自行 refresh，不依赖外部工具
- 零维护，永不过期（只要 refresh_token 有效）

### opencode 的凭证挂载架构（devcontainer 参考）

opencode 同样运行在容器中，通过 bind mount 透传宿主机认证文件：

```
宿主机: ~/.local/share/opencode/auth.json   (opencode 专属 auth 文件)
    ↓ bind mount（单文件）
devcontainer: /mnt/opencode-auth.json
    ↓ symlink (postCreateCommand)
devcontainer: ~/.local/share/opencode/auth.json
    ↓ opencode 读写
容器内自行 refresh → 写回宿主机文件
```

关键点：opencode 使用**独立的 auth 文件**（非 Claude CLI 的 `.credentials.json`），拥有**专属 refresh_token**，不与 CLI 竞争。本方案完全对标此模式。

## 2. 参考实现：opencode-anthropic-auth

源码: https://github.com/anomalyco/opencode-anthropic-auth (`index.mjs`, v0.0.13)

### OAuth 流程（PKCE + Authorization Code Grant）

```
用户执行 --login
    │
    ▼
生成 PKCE (code_verifier + code_challenge)
    │
    ▼
构造授权 URL:
  https://claude.ai/oauth/authorize
    ?client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e
    &response_type=code
    &redirect_uri=https://console.anthropic.com/oauth/code/callback
    &scope=org:create_api_key user:profile user:inference
    &code_challenge={S256 hash}
    &code_challenge_method=S256
    &state={verifier}
    &code=true
    │
    ▼
打开浏览器 → 用户授权 → 页面显示 authorization code
    │
    ▼
用户粘贴 code 到终端
    │
    ▼
POST https://console.anthropic.com/v1/oauth/token
  {
    code: "{code_part}",
    state: "{state_part}",        // code 格式: "{code}#{state}"
    grant_type: "authorization_code",
    client_id: "9d1c250a-...",
    redirect_uri: "https://console.anthropic.com/oauth/code/callback",
    code_verifier: "{verifier}"   // PKCE 验证
  }
    │
    ▼
返回: { access_token, refresh_token, expires_in }
  → 保存到 auth.json
```

### Token Refresh 流程

```javascript
// 每次请求前检查
if (!auth.access || auth.expires < Date.now()) {
  POST https://console.anthropic.com/v1/oauth/token
  {
    grant_type: "refresh_token",
    refresh_token: auth.refresh,
    client_id: "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
  }
  → 更新 auth.json（新 access_token + 新 refresh_token）
}
```

### API 请求头（OAuth 必需）

```
authorization: Bearer {access_token}
anthropic-beta: oauth-2025-04-20,interleaved-thinking-2025-05-14
user-agent: claude-cli/2.1.2 (external, cli)
```

## 3. 改造方案

### 3.1 架构

```
┌─────────────────────────────────────────────────────┐
│  一次性设置（宿主机终端）                              │
│                                                       │
│  $ node server.js --login                             │
│    → 生成 PKCE                                        │
│    → 打开浏览器 (claude.ai/oauth/authorize)           │
│    → 用户授权后粘贴 code                              │
│    → 换取 access_token + refresh_token                │
│    → 保存到 ~/.claude-max-proxy/auth.json              │
└──────────────────────┬──────────────────────────────┘
                       │
                       │ Docker volume mount (read-write)
                       │
┌──────────────────────▼──────────────────────────────┐
│  proxy 运行时（Docker 容器）                          │
│                                                       │
│  启动 → loadTokensFromFile()                          │
│    → 读取 /data/auth.json                             │
│    → 检查 expiresAt                                   │
│    → 如过期: doRefreshToken()                         │
│      → POST console.anthropic.com/v1/oauth/token      │
│      → 保存新 token pair 到 /data/auth.json           │
│    → 返回有效 access_token                            │
│                                                       │
│  每次请求 → getOAuthTokens()                          │
│    → 缓存有效 → 直接返回                              │
│    → 缓存过期 → 重新加载 + 自动 refresh               │
└─────────────────────────────────────────────────────┘
```

### 3.2 文件改动

#### `claude-max-proxy/server.js`

**A. 常量更新**

```javascript
const CLIENT_ID = '9d1c250a-e61b-44d9-88ed-5944d1962f5e';
const TOKEN_URL = 'https://console.anthropic.com/v1/oauth/token';
const AUTH_FILE = process.env.PROXY_AUTH_FILE || join(homedir(), '.claude-max-proxy', 'auth.json');
```

**B. 新增 `--login` CLI 模式**

```javascript
// 在 server.js 末尾，server.listen 之前
if (process.argv.includes('--login')) {
  (async () => {
    // 1. 生成 PKCE
    const { createHash, randomBytes } = await import('node:crypto');
    const verifier = randomBytes(32).toString('base64url');
    const challenge = createHash('sha256').update(verifier).digest('base64url');

    // 2. 构造授权 URL
    const url = new URL('https://claude.ai/oauth/authorize');
    url.searchParams.set('code', 'true');
    url.searchParams.set('client_id', CLIENT_ID);
    url.searchParams.set('response_type', 'code');
    url.searchParams.set('redirect_uri', 'https://console.anthropic.com/oauth/code/callback');
    url.searchParams.set('scope', 'org:create_api_key user:profile user:inference');
    url.searchParams.set('code_challenge', challenge);
    url.searchParams.set('code_challenge_method', 'S256');
    url.searchParams.set('state', verifier);
    // 注意：不设 access_type/prompt（Google OAuth 专属，Anthropic 不需要）

    console.log('\n=== Claude Max Proxy — OAuth Login ===\n');
    console.log('Opening browser for authorization...\n');

    // 3. 打开浏览器（跨平台）
    const { execSync } = await import('node:child_process');
    const openCmd = process.platform === 'darwin' ? 'open' : process.platform === 'win32' ? 'start' : 'xdg-open';
    try {
      execSync(`${openCmd} "${url.toString()}"`, { stdio: 'ignore' });
    } catch {
      console.log('Could not open browser automatically. Please visit:\n');
      console.log(url.toString());
      console.log();
    }

    // 4. 等待用户粘贴 code
    const readline = await import('node:readline');
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    const code = await new Promise(resolve => {
      rl.question('Paste the authorization code here: ', resolve);
    });
    rl.close();

    // 5. 换取 token
    const splits = code.trim().split('#');
    const response = await fetch(TOKEN_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code: splits[0],
        state: splits[1],
        grant_type: 'authorization_code',
        client_id: CLIENT_ID,
        redirect_uri: 'https://console.anthropic.com/oauth/code/callback',
        code_verifier: verifier,
      }),
    });

    if (!response.ok) {
      const err = await response.text();
      console.error('Authorization failed:', err);
      process.exit(1);
    }

    const json = await response.json();
    const tokens = {
      accessToken: json.access_token,
      refreshToken: json.refresh_token,
      expiresAt: Date.now() + json.expires_in * 1000,
    };

    // 6. 保存（自动创建目录）
    const { dirname } = await import('node:path');
    const { mkdirSync } = await import('node:fs');
    mkdirSync(dirname(AUTH_FILE), { recursive: true });
    writeFileSync(AUTH_FILE, JSON.stringify(tokens, null, 2), { mode: 0o600 });
    const hoursLeft = (json.expires_in / 3600).toFixed(1);
    console.log(`\nSuccess! Token saved to ${AUTH_FILE}`);
    console.log(`Access token valid for ${hoursLeft}h, refresh token will auto-renew.`);
    process.exit(0);
  })();
} else {
  // 正常 server 启动逻辑（现有代码）
}
```

**C. 修改 `loadTokensFromFile()`**

```javascript
function loadTokensFromFile() {
  try {
    // 优先读 proxy 专属 auth 文件
    if (existsSync(AUTH_FILE)) {
      const data = JSON.parse(readFileSync(AUTH_FILE, 'utf8'));
      if (data.accessToken) return data;
    }
    // 兼容: CLI 嵌套格式 (~/.claude/.credentials.json)
    const legacyFile = join(homedir(), '.claude', '.credentials.json');
    if (existsSync(legacyFile)) {
      const data = JSON.parse(readFileSync(legacyFile, 'utf8'));
      if (data.claudeAiOauth?.accessToken) return data.claudeAiOauth;
    }
  } catch (e) {}
  return null;
}
```

**D. 恢复并修正 `doRefreshToken()`**

```javascript
async function doRefreshToken(refreshTok) {
  try {
    console.log('[TOKEN REFRESH] Attempting token refresh...');
    const response = await fetch(TOKEN_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        grant_type: 'refresh_token',
        refresh_token: refreshTok,
        client_id: CLIENT_ID,
      }),
    });
    if (!response.ok) {
      const err = await response.text();
      console.error(`[TOKEN REFRESH FAILED] Status ${response.status}: ${err}`);
      console.error('[TOKEN REFRESH FAILED] Fix: run "node server.js --login" on the host to re-authorize.');
      return null;
    }
    const data = await response.json();
    console.log(`[TOKEN REFRESH] Success, new token valid for ${(data.expires_in / 3600).toFixed(1)}h`);
    return {
      accessToken: data.access_token,
      refreshToken: data.refresh_token || refreshTok,
      expiresAt: Date.now() + (data.expires_in * 1000),
    };
  } catch (e) {
    console.error(`[TOKEN REFRESH ERROR] ${e.message}`);
    return null;
  }
}
```

**E. 恢复 `getOAuthTokens()` 的 auto-refresh**

```javascript
async function getOAuthTokens() {
  if (cachedTokens && Date.now() < tokenExpiry - 300000) return cachedTokens;
  let oauth = loadTokensFromEnv() || loadTokensFromFile() || loadTokensFromKeychain();
  if (!oauth?.accessToken) {
    throw new Error('No OAuth tokens found. Run "node server.js --login" on the host to authorize.');
  }

  // Auto-refresh if within 5 min of expiry or already expired
  if (oauth.expiresAt && Date.now() >= oauth.expiresAt - 300000 && oauth.refreshToken) {
    const refreshed = await doRefreshToken(oauth.refreshToken);
    if (refreshed) {
      saveTokensToFile(refreshed);
      cachedTokens = refreshed;
      tokenExpiry = refreshed.expiresAt;
      return refreshed;
    }
    // Refresh failed — fall through with expired token (will get 401 from Anthropic)
    console.error('[TOKEN] Refresh failed, using expired token. Re-run "node server.js --login".');
  }

  // Token health logging
  const now = Date.now();
  if (oauth.expiresAt && now >= oauth.expiresAt) {
    const expiredAgo = ((now - oauth.expiresAt) / 3600000).toFixed(1);
    console.error(`[TOKEN EXPIRED] ${expiredAgo}h ago. Fix: run "node server.js --login" on the host.`);
  } else if (oauth.expiresAt && oauth.expiresAt - now < 1800000) {
    const minsLeft = ((oauth.expiresAt - now) / 60000).toFixed(0);
    console.warn(`[TOKEN WARNING] Expires in ${minsLeft} min.`);
  }

  cachedTokens = oauth;
  tokenExpiry = oauth.expiresAt || Date.now() + 3600000;
  return oauth;
}
```

**F. 修正 `saveTokensToFile()`**

```javascript
function saveTokensToFile(tokens) {
  try {
    writeFileSync(AUTH_FILE, JSON.stringify(tokens, null, 2), { mode: 0o600 });
  } catch (e) {
    console.error(`[TOKEN SAVE ERROR] Could not write to ${AUTH_FILE}: ${e.message}`);
  }
}
```

**G. API 请求头 + URL 参数注入**

在 `handleChat()` 中构造 Anthropic API 请求时：

```javascript
// Headers（OAuth 必需）
headers['authorization'] = `Bearer ${tokens.accessToken}`;
headers['anthropic-beta'] = 'oauth-2025-04-20,interleaved-thinking-2025-05-14';
headers['user-agent'] = 'claude-cli/2.1.2 (external, cli)';
delete headers['x-api-key'];

// URL query parameter（opencode 同样添加，OAuth 模式下可能必需）
const apiUrl = new URL(ANTHROPIC_API_URL);
apiUrl.searchParams.set('beta', 'true');
// 使用 apiUrl.toString() 作为 fetch URL
```

#### `docker-compose.yml`

```yaml
claude-max-proxy:
  volumes:
    - ${PROXY_AUTH_DIR:?请在 .env 中设置 PROXY_AUTH_DIR}:/data:rw
  environment:
    - HOST=0.0.0.0
    - PROXY_AUTH_FILE=/data/auth.json
```

注意: 挂载为 **read-write**（proxy 需要写入 refreshed token）。

#### `.env` / `.env.example`

```env
# claude-max-proxy 独立认证（proxy 自有 OAuth，自动 refresh）
PROXY_AUTH_DIR=~/.claude-max-proxy
```

### 3.3 使用流程

#### 首次设置（一次性）

```bash
# 1. 在宿主机创建 auth 目录
mkdir -p ~/.claude-max-proxy

# 2. 运行 OAuth 登录
cd <path-to>/claude-max-proxy
node server.js --login
# → 浏览器打开 claude.ai 授权页面
# → 授权后页面显示 code
# → 粘贴 code 到终端
# → 保存到 ~/.claude-max-proxy/auth.json (由 PROXY_AUTH_FILE 指定)

# 3. 启动服务
cd <path-to>/mentor-agent-service
docker compose up -d claude-max-proxy
```

#### 日常使用

无需任何人工干预。Proxy 自动 refresh token，新 token 写回 `auth.json`。

#### 异常恢复

如果 refresh_token 也过期（长期未使用 proxy）:
```bash
node server.js --login   # 重新授权
docker compose restart claude-max-proxy
```

## 4. 对比总结

| | 旧方案（静态导出） | 阶段 1（只读挂载） | 新方案（独立 OAuth） |
|---|---|---|---|
| 初始设置 | 手动从 Keychain 导出 | 挂载 ~/.claude/ 目录 | `node server.js --login` |
| Token 刷新 | 无法刷新 | 依赖 host CLI + Keychain | **proxy 自行 refresh** |
| Refresh token | 与 CLI 共享（竞争） | 与 CLI 共享（竞争） | **proxy 独占** |
| 文件同步问题 | 手动导出后即过时 | Keychain 不写文件 | **无（自行管理）** |
| 维护成本 | 每次过期手动导出 | 需 launchd 同步脚本 | **零维护** |
| 可靠性 | 低 | 中 | **高** |

## 5. 自查对照记录（vs opencode 源码）

对照 `opencode-anthropic-auth@0.0.13` 完整源码（`index.mjs`）逐项核对：

- **已修正**: 删除 `access_type=offline` 和 `prompt=consent`（Google OAuth 专属，opencode 未使用）
- **已修正**: 添加 `?beta=true` URL query parameter（opencode 在所有 `/v1/messages` 请求上追加）
- **已修正**: `AUTH_FILE` 默认路径从 `~/.claude-max-proxy-auth.json` 改为 `~/.claude-max-proxy/auth.json`（对齐目录挂载）
- **已修正**: 浏览器打开命令跨平台兼容（macOS/Linux/Windows）
- **确认一致**: client_id、authorize URL、token URL、code 格式、PKCE flow、exchange/refresh body、所有必需 headers
- **我们更优**: token refresh 提前 5 分钟主动触发（opencode 是过期后才 refresh）
- **不适用**: tool name `mcp_` 前缀、system prompt 重写、streaming response 替换（opencode 特有 workaround）

## 6. 风险与注意事项

1. **client_id 稳定性**: 使用 Claude Code CLI 官方的 `9d1c250a-...`。如果 Anthropic 再次更换，需要更新。可以改为从环境变量注入以便快速修改。
2. **OAuth scope**: opencode 请求 `org:create_api_key user:profile user:inference`。proxy 只需要 `user:inference`，但为安全起见保持一致。
3. **user-agent 伪装**: opencode 使用 `claude-cli/2.1.2 (external, cli)`。这是 Anthropic 允许的 OAuth 客户端标识，需要保持。
4. **并发安全**: 如果多个请求同时触发 refresh，可能出现 race condition。可以加一个 mutex，但初期不是必须的（proxy 是单进程 Node.js）。
5. **Anthropic ToS**: 使用 OAuth subscription token 通过 proxy 访问 API 属于灰色地带。参考 [Anthropic 认证使用政策](https://github.com/AndyMik90/Auto-Claude/issues/1871)，需关注政策变化。
