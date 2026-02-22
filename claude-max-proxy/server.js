#!/usr/bin/env node

/**
 * Claude Max Proxy v4.0.0 - Independent OAuth
 * - PKCE OAuth login via `--login` CLI mode (one-time, on host)
 * - Auto token refresh with dedicated refresh_token (no CLI competition)
 * - XML tool call history reconstruction
 */

import { createServer } from 'node:http';
import { execSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

const PORT = process.env.PORT || 3456;
const HOST = process.env.HOST || '127.0.0.1';
const ANTHROPIC_API_URL = 'https://api.anthropic.com/v1/messages';

const CLIENT_ID = '9d1c250a-e61b-44d9-88ed-5944d1962f5e';
const TOKEN_URL = 'https://console.anthropic.com/v1/oauth/token';

const CLAUDE_CODE_SYSTEM = "You are Claude Code, Anthropic's official CLI for Claude.";

const MODEL_MAP = {
  'claude-sonnet-4': 'claude-sonnet-4-5-20250929',
  'claude-opus-4': 'claude-opus-4-5-20251101',
  'claude-opus-4-5': 'claude-opus-4-5-20251101',
  'claude-opus-4-6': 'claude-opus-4-6',
  'claude-sonnet-4-5': 'claude-sonnet-4-5-20250929',
  'claude-sonnet-4-6': 'claude-sonnet-4-6',
  'claude-haiku-4-5': 'claude-haiku-4-5-20251001',
  'opus': 'claude-opus-4-5-20251101',
  'sonnet': 'claude-sonnet-4-5-20250929',
  'haiku': 'claude-3-5-haiku-20241022',
  'gpt-4': 'claude-opus-4-5-20251101',
  'gpt-4o': 'claude-sonnet-4-5-20250929',
  'gpt-3.5-turbo': 'claude-3-5-haiku-20241022',
  'openai/claude-opus-4-5': 'claude-opus-4-5-20251101',
  'openai/claude-opus-4-6': 'claude-opus-4-6',
  'openai/claude-sonnet-4-5': 'claude-sonnet-4-5-20250929',
  'openai/claude-sonnet-4-6': 'claude-sonnet-4-6',
  'openai/claude-haiku-4-5': 'claude-haiku-4-5-20251001',
  'openai/claude-haiku-4': 'claude-3-5-haiku-20241022',
};

const AVAILABLE_MODELS = [
  { id: 'claude-opus-4-5', name: 'Claude Opus 4.5' },
  { id: 'claude-opus-4-6', name: 'Claude Opus 4.6' },
  { id: 'claude-sonnet-4-5', name: 'Claude Sonnet 4.5' },
  { id: 'claude-sonnet-4-6', name: 'Claude Sonnet 4.6' },
  { id: 'claude-haiku-4-5', name: 'Claude Haiku 4.5' },
];

// Proxy's own auth file (independent OAuth, not shared with CLI).
// In Docker: PROXY_AUTH_FILE=/data/auth.json (volume-mounted from host ~/.claude-max-proxy/)
const AUTH_FILE = process.env.PROXY_AUTH_FILE || join(homedir(), '.claude-max-proxy', 'auth.json');

let cachedTokens = null;
let tokenExpiry = 0;

function loadTokensFromEnv() {
  const accessToken = process.env.CLAUDE_ACCESS_TOKEN;
  if (accessToken) return { accessToken, expiresAt: Date.now() + 86400000 };
  return null;
}

function loadTokensFromFile() {
  try {
    // Priority: proxy's own auth file
    if (existsSync(AUTH_FILE)) {
      const data = JSON.parse(readFileSync(AUTH_FILE, 'utf8'));
      if (data.accessToken) return data;
    }
    // Fallback: CLI nested format (~/.claude/.credentials.json)
    const legacyFile = join(homedir(), '.claude', '.credentials.json');
    if (existsSync(legacyFile)) {
      const data = JSON.parse(readFileSync(legacyFile, 'utf8'));
      if (data.claudeAiOauth?.accessToken) return data.claudeAiOauth;
    }
  } catch (e) {}
  return null;
}

function loadTokensFromKeychain() {
  if (process.platform !== 'darwin') return null;
  try {
    const output = execSync('security find-generic-password -s "Claude Code-credentials" -w', { encoding: 'utf8', timeout: 5000 }).trim();
    return JSON.parse(output).claudeAiOauth;
  } catch (e) { return null; }
}

function saveTokensToFile(tokens) {
  try {
    writeFileSync(AUTH_FILE, JSON.stringify(tokens, null, 2), { mode: 0o600 });
  } catch (e) {
    console.error(`[TOKEN SAVE ERROR] Could not write to ${AUTH_FILE}: ${e.message}`);
  }
}

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

function buildToolContext(tools, systemPrompts) {
  let context = '';
  if (systemPrompts && systemPrompts.length > 0) {
    context += '[Assistant Identity]\n' + systemPrompts.join('\n') + '\n\n';
  }
  if (tools && tools.length > 0) {
    const defs = tools.map(t => {
      const fn = t.function || t;
      return `- ${fn.name}: ${fn.description || 'No description'}`;
    }).join('\n');
    context += '[Available Tools]\n' + defs + '\n\n[Tool Usage]\nWhen you need to use a tool, output XML:\n<function_calls>\n<invoke name="TOOL_NAME">\n<parameter name="PARAM">VALUE</parameter>\n</invoke>\n</function_calls>\nDo NOT show the XML to the user or explain it. Just use it silently.\n\n';
  }
  return context;
}

function parseXmlToolCalls(text) {
  const toolCalls = [];
  const regex = /<function_calls>([\s\S]*?)<\/function_calls>/g;
  let match;
  while ((match = regex.exec(text)) !== null) {
    const invokeRegex = /<invoke\s+name="([^"]+)">([\s\S]*?)<\/invoke>/g;
    let invokeMatch;
    while ((invokeMatch = invokeRegex.exec(match[1])) !== null) {
      const params = {};
      const paramRegex = /<parameter\s+name="([^"]+)">([\s\S]*?)<\/parameter>/g;
      let paramMatch;
      while ((paramMatch = paramRegex.exec(invokeMatch[2])) !== null) {
        params[paramMatch[1]] = paramMatch[2];
      }
      toolCalls.push({
        id: 'call_' + randomUUID().split('-')[0],
        type: 'function',
        function: { name: invokeMatch[1], arguments: JSON.stringify(params) }
      });
    }
  }
  const cleanText = text.replace(/<function_calls>[\s\S]*?<\/function_calls>/g, '').trim();
  return { toolCalls, cleanText };
}

// Convert tool_calls back to XML format for Claude's understanding
function toolCallsToXml(toolCalls) {
  if (!toolCalls || toolCalls.length === 0) return '';

  let xml = '<function_calls>\n';
  for (const call of toolCalls) {
    const fn = call.function;
    let args = {};
    try { args = JSON.parse(fn.arguments || '{}'); } catch (e) {}

    xml += `<invoke name="${fn.name}">\n`;
    for (const [key, value] of Object.entries(args)) {
      xml += `<parameter name="${key}">${value}</parameter>\n`;
    }
    xml += '</invoke>\n';
  }
  xml += '</function_calls>';
  return xml;
}

function extractText(content) {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) return content.filter(c => c.type === 'text').map(c => c.text).join('\n');
  return content?.text || '';
}

function convertMessages(messages, tools) {
  let systemPrompts = [];
  const anthropicMessages = [];

  for (const msg of messages) {
    if (msg.role === 'system') {
      systemPrompts.push(extractText(msg.content));
    } else if (msg.role === 'user') {
      const content = extractText(msg.content);
      if (content) {
        anthropicMessages.push({ role: 'user', content });
      }
    } else if (msg.role === 'assistant') {
      let content = extractText(msg.content);

      // If assistant message has tool_calls but no/empty content,
      // reconstruct the XML tool call format so Claude recognizes it as its own action
      if ((!content || content.trim() === '' || content === '[Using tools...]') && msg.tool_calls && msg.tool_calls.length > 0) {
        content = toolCallsToXml(msg.tool_calls);
      }

      // Skip completely empty assistant messages
      if (content && content.trim()) {
        anthropicMessages.push({ role: 'assistant', content });
      }
    } else if (msg.role === 'tool') {
      const content = `[Tool Result: ${msg.tool_call_id}]\n${extractText(msg.content)}`;
      anthropicMessages.push({ role: 'user', content });
    }
  }

  // Ensure we don't have consecutive same-role messages (merge)
  const fixedMessages = [];
  for (const msg of anthropicMessages) {
    if (fixedMessages.length > 0 && fixedMessages[fixedMessages.length - 1].role === msg.role) {
      fixedMessages[fixedMessages.length - 1].content += '\n\n' + msg.content;
    } else {
      fixedMessages.push(msg);
    }
  }

  // Inject tool context into first user message
  const toolContext = buildToolContext(tools, systemPrompts);
  if (toolContext && fixedMessages.length > 0) {
    for (let i = 0; i < fixedMessages.length; i++) {
      if (fixedMessages[i].role === 'user') {
        fixedMessages[i].content = toolContext + '[User Message]\n' + fixedMessages[i].content;
        break;
      }
    }
  }

  return { system: CLAUDE_CODE_SYSTEM, messages: fixedMessages };
}

async function handleChat(req, res, body) {
  const { model, messages, temperature, max_tokens, tools, stream } = body;
  const mappedModel = MODEL_MAP[model] || MODEL_MAP['claude-sonnet-4'];
  const { system, messages: anthropicMessages } = convertMessages(messages, tools);
  const hasTools = tools && tools.length > 0;

  console.log(`[${stream ? 'STREAM' : 'SYNC'}] model=${mappedModel}, tools=${tools?.length || 0}, msgs=${anthropicMessages.length}`);

  const requestId = `chatcmpl-${randomUUID()}`;
  const created = Math.floor(Date.now() / 1000);

  let tokens;
  try { tokens = await getOAuthTokens(); }
  catch (e) { return sendJSON(res, 401, { error: { message: e.message } }); }

  // OAuth API URL with ?beta=true (required for OAuth mode, aligned with opencode)
  const apiUrl = new URL(ANTHROPIC_API_URL);
  apiUrl.searchParams.set('beta', 'true');
  const apiUrlStr = apiUrl.toString();

  const apiHeaders = {
    'Authorization': `Bearer ${tokens.accessToken}`,
    'Content-Type': 'application/json',
    'anthropic-version': '2023-06-01',
    'anthropic-beta': 'oauth-2025-04-20,interleaved-thinking-2025-05-14',
    'user-agent': 'claude-cli/2.1.2 (external, cli)',
  };

  const requestBody = {
    model: mappedModel,
    system: system,
    messages: anthropicMessages,
    max_tokens: max_tokens || 8192,
  };
  if (temperature !== undefined) requestBody.temperature = temperature;

  // For tool requests, use sync to ensure XML is filtered before sending
  if (stream && !hasTools) {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'Access-Control-Allow-Origin': '*',
    });

    try {
      const response = await fetch(apiUrlStr, {
        method: 'POST',
        headers: apiHeaders,
        body: JSON.stringify({ ...requestBody, stream: true }),
      });

      if (!response.ok) {
        const error = await response.text();
        console.error('API error:', response.status, error);
        res.write(`data: ${JSON.stringify({ error: { message: error } })}\n\n`);
        res.write('data: [DONE]\n\n');
        return res.end();
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const data = line.slice(6);
          if (data === '[DONE]') continue;
          try {
            const event = JSON.parse(data);
            if (event.type === 'content_block_delta' && event.delta?.text) {
              res.write(`data: ${JSON.stringify({
                id: requestId, object: 'chat.completion.chunk', created, model,
                choices: [{ index: 0, delta: { content: event.delta.text }, finish_reason: null }]
              })}\n\n`);
            } else if (event.type === 'message_stop') {
              res.write(`data: ${JSON.stringify({
                id: requestId, object: 'chat.completion.chunk', created, model,
                choices: [{ index: 0, delta: {}, finish_reason: 'stop' }]
              })}\n\n`);
            }
          } catch (e) {}
        }
      }
      res.write('data: [DONE]\n\n');
      res.end();
    } catch (e) {
      console.error('Stream error:', e);
      res.write(`data: ${JSON.stringify({ error: { message: e.message } })}\n\n`);
      res.write('data: [DONE]\n\n');
      res.end();
    }
  } else {
    // Sync mode for tool requests
    try {
      const response = await fetch(apiUrlStr, {
        method: 'POST',
        headers: apiHeaders,
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        const error = await response.text();
        console.error('API error:', response.status, error);
        return sendJSON(res, response.status, { error: { message: error } });
      }

      const data = await response.json();
      const text = (data.content || []).filter(b => b.type === 'text').map(b => b.text).join('\n');
      const { toolCalls, cleanText } = parseXmlToolCalls(text);

      // For response to client: null content is OK when we have tool_calls
      const finalContent = cleanText || (toolCalls.length > 0 ? null : 'Done.');

      const message = { role: 'assistant', content: finalContent };
      if (toolCalls.length > 0) message.tool_calls = toolCalls;

      if (stream) {
        res.writeHead(200, {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Connection': 'keep-alive',
          'Access-Control-Allow-Origin': '*',
        });

        if (finalContent) {
          res.write(`data: ${JSON.stringify({
            id: requestId, object: 'chat.completion.chunk', created, model,
            choices: [{ index: 0, delta: { content: finalContent }, finish_reason: null }]
          })}\n\n`);
        }

        if (toolCalls.length > 0) {
          res.write(`data: ${JSON.stringify({
            id: requestId, object: 'chat.completion.chunk', created, model,
            choices: [{ index: 0, delta: { tool_calls: toolCalls }, finish_reason: 'tool_calls' }]
          })}\n\n`);
        } else {
          res.write(`data: ${JSON.stringify({
            id: requestId, object: 'chat.completion.chunk', created, model,
            choices: [{ index: 0, delta: {}, finish_reason: 'stop' }]
          })}\n\n`);
        }

        res.write('data: [DONE]\n\n');
        res.end();
      } else {
        sendJSON(res, 200, {
          id: requestId, object: 'chat.completion', created, model,
          choices: [{ index: 0, message, finish_reason: toolCalls.length > 0 ? 'tool_calls' : 'stop' }],
          usage: { prompt_tokens: data.usage?.input_tokens || -1, completion_tokens: data.usage?.output_tokens || -1, total_tokens: (data.usage?.input_tokens || 0) + (data.usage?.output_tokens || 0) },
        });
      }
    } catch (e) {
      console.error('Error:', e);
      sendJSON(res, 500, { error: { message: e.message } });
    }
  }
}

function sendJSON(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
  res.end(JSON.stringify(data));
}

async function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => { try { resolve(body ? JSON.parse(body) : {}); } catch (e) { reject(new Error('Invalid JSON')); } });
    req.on('error', reject);
  });
}

async function handleRequest(req, res) {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const path = url.pathname;
  const method = req.method;

  if (method === 'OPTIONS') {
    res.writeHead(204, { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type, Authorization' });
    return res.end();
  }

  if (path === '/health' || path === '/') {
    try {
      await getOAuthTokens();
      return sendJSON(res, 200, { status: 'ok', version: '4.0.0', mode: 'independent-oauth', features: ['oauth', 'auto-refresh', 'tools', 'xml-history'] });
    } catch (e) {
      return sendJSON(res, 200, { status: 'error', version: '4.0.0', error: e.message });
    }
  }

  if (path === '/v1/models' && method === 'GET') {
    return sendJSON(res, 200, { object: 'list', data: AVAILABLE_MODELS.map(m => ({ id: m.id, object: 'model', created: 1700000000, owned_by: 'anthropic' })) });
  }

  if (path === '/v1/chat/completions' && method === 'POST') {
    try {
      const body = await parseBody(req);
      if (!body.messages) return sendJSON(res, 400, { error: { message: 'messages required' } });
      return handleChat(req, res, body);
    } catch (e) {
      return sendJSON(res, 500, { error: { message: e.message } });
    }
  }

  sendJSON(res, 404, { error: { message: 'Not found' } });
}

// ─── CLI: --login (one-time OAuth authorization on host) ───
if (process.argv.includes('--login')) {
  (async () => {
    // 1. Generate PKCE
    const { createHash, randomBytes } = await import('node:crypto');
    const verifier = randomBytes(32).toString('base64url');
    const challenge = createHash('sha256').update(verifier).digest('base64url');

    // 2. Build authorization URL
    const authUrl = new URL('https://claude.ai/oauth/authorize');
    authUrl.searchParams.set('code', 'true');
    authUrl.searchParams.set('client_id', CLIENT_ID);
    authUrl.searchParams.set('response_type', 'code');
    authUrl.searchParams.set('redirect_uri', 'https://console.anthropic.com/oauth/code/callback');
    authUrl.searchParams.set('scope', 'org:create_api_key user:profile user:inference');
    authUrl.searchParams.set('code_challenge', challenge);
    authUrl.searchParams.set('code_challenge_method', 'S256');
    authUrl.searchParams.set('state', verifier);

    console.log('\n=== Claude Max Proxy — OAuth Login ===\n');
    console.log('Opening browser for authorization...\n');

    // 3. Open browser (cross-platform)
    const openCmd = process.platform === 'darwin' ? 'open' : process.platform === 'win32' ? 'start' : 'xdg-open';
    try {
      execSync(`${openCmd} "${authUrl.toString()}"`, { stdio: 'ignore' });
    } catch {
      console.log('Could not open browser automatically. Please visit:\n');
      console.log(authUrl.toString());
      console.log();
    }

    // 4. Wait for user to paste authorization code
    const readline = await import('node:readline');
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    const code = await new Promise(resolve => {
      rl.question('Paste the authorization code here: ', resolve);
    });
    rl.close();

    // 5. Exchange code for tokens
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

    // 6. Save (auto-create directory)
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
  // ─── Normal server startup ───
  const server = createServer(handleRequest);
  server.listen(PORT, HOST, async () => {
    let status = 'checking...';
    try {
      const tokens = await getOAuthTokens();
      if (tokens.expiresAt && Date.now() >= tokens.expiresAt) {
        status = 'EXPIRED — run "node server.js --login" on host';
      } else if (tokens.expiresAt) {
        const hoursLeft = ((tokens.expiresAt - Date.now()) / 3600000).toFixed(1);
        status = `valid (${hoursLeft}h remaining)`;
      } else {
        status = 'valid (no expiry info)';
      }
    } catch (e) { status = e.message; }
    console.log(`
╔═══════════════════════════════════════════════════════════════╗
║     Claude Max Proxy v4.0.0 (Independent OAuth)               ║
╠═══════════════════════════════════════════════════════════════╣
║  Server: http://${HOST}:${PORT}                                   ║
║  Token:  ${status.padEnd(45)}║
║  Auth:   ${AUTH_FILE.padEnd(45)}║
╚═══════════════════════════════════════════════════════════════╝
`);
  });

  process.on('SIGTERM', () => { server.close(() => process.exit(0)); });
  process.on('SIGINT', () => { server.close(() => process.exit(0)); });
}
