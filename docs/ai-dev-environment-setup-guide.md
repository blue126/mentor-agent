# AI 开发环境标准化配置指南

版本: v1.5
日期: 2026-02-13
适用范围: 任何使用 Claude Code / OpenCode / Codex CLI 的项目

---

## 概述

本文档记录了为项目配置完整 AI 辅助开发环境的标准化流程。涵盖三个层面：

1. **Devcontainer** — 容器化开发环境，确保 AI 工具一致安装
2. **Subagent** — 领域专精 AI 子代理，按技术栈委派任务
3. **Codex CLI + Settings + Skills** — 跨模型协作配置与可复用技能

完成本指南后，项目将具备：
- 三个 AI CLI 工具开箱即用（Claude Code、OpenCode、Codex CLI）
- 按技术领域自动委派的 subagent 体系
- 跨模型代码审查能力（Claude 写码、Codex 5.3 审码）
- 可复用的 Claude Code Skills（如 `/codex` 斜杠命令）
- 两套 IDE 环境无缝切换（OpenCode 为主、Claude Code 为备）

### 如何使用本指南

本指南是**通用模板**，描述了每个步骤该做什么，但不包含特定项目的技术栈细节。
推荐的使用方式是：让 AI 结合你的项目上下文，生成**项目专属的集成方案**。
根据项目阶段，选择对应的场景：

> **关于 BMAD**：两个场景都使用了 [BMAD 方法论](https://github.com/bmad-code-org/bmad-method) 的产出物。
> 如果你的项目尚未安装 BMAD，请先参照其官方文档完成安装（`_bmad/` 目录）。
> 如果不使用 BMAD，可以跳过以下 prompt，直接按 Section 1-3 手动配置。

#### 场景 A：Brownfield 项目（已有代码库）

先运行 BMAD 的 `/bmad-bmm-generate-project-context` 命令，生成 `project-context.md`。
该命令会自动扫描项目代码、配置文件和目录结构，输出一份包含技术栈、编码规范和关键约束的项目概览。
然后将概览和本指南一起交给 AI 生成集成方案。直接复制粘贴以下 prompt：

```
请读取以下两个文件，生成本项目的 AI subagent 集成方案：
1. AI 开发环境配置指南：docs/ai-dev-environment-setup-guide.md
2. 项目上下文概览：_bmad-output/project-context.md

基于 project-context.md 中描述的技术栈和架构：
1. 从指南 Section 2.2 的 subagent 菜单中选出本项目需要的 subagent，说明选型理由
2. 为每个实现类 subagent 编写项目专属上下文块（从 project-context.md 中提取关键约束）
3. 生成两套 agent 定义文件的完整内容（OpenCode 格式 + Claude Code 格式）
4. 读取 _bmad/bmm/workflows/ 下的实际 workflow 文件，给出具体的修改内容（引用文件路径和行号）
5. 生成验证清单

输出为一份完整的 markdown 文档，保存到 docs/ 目录下。
```

#### 场景 B：Greenfield 项目（从零开始）

先用 BMAD 方法论完成项目规划（至少完成架构设计和技术栈选型），确保以下产出物存在：
- `_bmad-output/architecture.md` — 技术栈选型和架构决策
- `_bmad-output/project-brief.md` — 项目简报

技术栈确定后，再执行以下 prompt 生成集成方案：

```
请读取以下文件，生成本项目的 AI subagent 集成方案：
1. AI 开发环境配置指南：docs/ai-dev-environment-setup-guide.md
2. 架构文档：_bmad-output/architecture.md
3. 项目简报：_bmad-output/project-brief.md

基于架构文档中确定的技术栈：
1. 从指南 Section 2.2 的 subagent 菜单中选出本项目需要的 subagent，说明选型理由
2. 根据架构文档的技术选型，为每个实现类 subagent 编写项目专属上下文块
3. 生成两套 agent 定义文件的完整内容（OpenCode 格式 + Claude Code 格式）
4. 读取 _bmad/bmm/workflows/ 下的实际 workflow 文件，给出具体的修改内容（引用文件路径和行号）
5. 生成验证清单

输出为一份完整的 markdown 文档，保存到 docs/ 目录下。
```

参考案例：[LaaS v2 集成方案](improvement/bmad-subagent-integration-plan.md) 就是用这种方式生成的。

---

## 目录

0. [前置条件](#0-前置条件)
1. [Devcontainer 标准化](#1-devcontainer-标准化)
2. [Subagent 选型与创建](#2-subagent-选型与创建)
3. [Codex CLI、Settings 与 Skills 配置](#3-codex-clisettings-与-skills-配置)
4. [BMAD Workflow 集成（可选）](#4-bmad-workflow-集成可选)
5. [验证清单](#5-验证清单)
6. [附录：文件清单模板](#6-附录文件清单模板)

---

## 0. 前置条件

开始配置前，确保宿主机（你的 Mac/Linux/Windows）已完成以下准备。

### 0.1 宿主机软件

| 软件 | 用途 | 安装方式 |
|---|---|---|
| VS Code | 主编辑器 | https://code.visualstudio.com/ |
| Dev Containers 扩展 | 在 VS Code 中运行容器化开发环境 | VS Code 扩展市场搜索 `ms-vscode-remote.remote-containers` |
| Docker Desktop | 容器运行时 | https://www.docker.com/products/docker-desktop/ |

### 0.2 AI 工具认证（宿主机上完成）

三个 AI CLI 工具各有独立的认证体系，必须在**宿主机上**提前完成认证，
容器通过挂载凭证文件来复用宿主机的登录状态。

#### Claude Code

在宿主机终端运行：

```bash
npm install -g @anthropic-ai/claude-code
claude login
```

认证完成后凭证自动存储。容器内的 Claude Code 通常通过 VS Code Dev Containers 扩展自动继承宿主机的认证状态，无需额外配置。
如果容器内 `claude -p "say hi"` 报认证错误，可在容器终端重新运行 `claude login`。

#### OpenCode

在宿主机终端运行：

```bash
npm install -g opencode
opencode auth login    # 按提示完成 OAuth 认证（Anthropic、OpenAI、Google 等）
```

认证完成后凭证写入项目目录 `.opencode/auth.json`。
容器通过 bind mount 将此文件挂载到 `/mnt/`，再 symlink 到容器内 OpenCode 期望的路径
（Linux: `~/.local/share/opencode/auth.json`）。

> **各平台凭证默认路径**（OpenCode 遵循 XDG/平台标准）：
> - macOS: `~/Library/Application Support/opencode/auth.json`
> - Linux: `~/.local/share/opencode/auth.json`
> - Windows: `%APPDATA%\opencode\auth.json`
>
> 如果 `opencode auth login` 将凭证写入了上述全局路径而非项目目录，
> 需将 Section 1.3 的 mount source 改为对应的宿主机全局路径。

#### Codex CLI

macOS 默认使用 Keychain 存储凭证，容器内无法访问。需要切换为文件存储模式：

```bash
npm install -g @openai/codex

# 1. 切换为文件存储（写入 ~/.codex/config.toml）
mkdir -p ~/.codex
echo 'cli_auth_credentials_store = "file"' >> ~/.codex/config.toml

# 2. 登录（使用 device-auth 以兼容无浏览器环境）
codex login --device-auth
```

认证完成后凭证写入 `~/.codex/auth.json`，容器通过 bind mount 挂载此文件。

> **注意**：如果宿主机上这些凭证文件不存在，devcontainer 的 bind mount 会报错导致容器启动失败。
> 请确保认证步骤全部完成后再 build 容器。

---

## 1. Devcontainer 标准化

### 1.1 Dockerfile

使用 `ubuntu-24.04` 基础镜像（不绑定特定语言运行时，由 features 按需安装）：

```dockerfile
FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

# 替换 apt 源为就近镜像，加速 Feature 安装
RUN sed -i 's|http://ports.ubuntu.com|http://mirror.aarnet.edu.au|g' /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || \
    sed -i 's|http://ports.ubuntu.com|http://mirror.aarnet.edu.au|g' /etc/apt/sources.list 2>/dev/null || true
RUN apt-get update
```

> **为什么不用 `python:3.x` 或 `node:lts` 基础镜像？**
> 基础镜像只负责 OS 层面的设置（如 apt mirror）。语言运行时通过 devcontainer features 安装，
> 这样 features 的 apt 操作也能使用替换后的镜像源。

> **apt 镜像源**：示例中的 `mirror.aarnet.edu.au` 是澳洲镜像。请替换为你所在地区的就近镜像，
> 如中国大陆 `mirrors.aliyun.com`、美国 `us.archive.ubuntu.com`、欧洲 `de.archive.ubuntu.com` 等。
> 如果不需要替换 apt 源，可以删除 Dockerfile 中的两行 `RUN sed` 命令。

### 1.2 Features — 三个 AI 工具

```jsonc
"features": {
    // === 语言运行时（按项目需要增删）===
    "ghcr.io/devcontainers/features/python:1": { "version": "3.12" },
    "ghcr.io/devcontainers/features/node:1": { "version": "lts" },

    // === 通用工具 ===
    "ghcr.io/devcontainers/features/docker-outside-of-docker:1": {},
    "ghcr.io/devcontainers/features/github-cli:1": {},

    // === AI CLI 工具（核心三件套）===
    // OpenCode — 终端 AI 编程助手，支持多模型切换
    "ghcr.io/jsburckhardt/devcontainer-features/opencode:1": {},
    // Codex CLI — OpenAI 编程助手（用于 Claude Code 中的跨模型代码审查）
    "ghcr.io/jsburckhardt/devcontainer-features/codex:1": {},
    // Claude Code — Anthropic 官方 CLI（版本固定为 1.0）
    "ghcr.io/anthropics/devcontainer-features/claude-code:1.0": {}
}
```

**关键原则**：

| 原则 | 说明 |
|---|---|
| 用 features 安装，不用 npm install -g | features 在 build time 安装，更可靠且可缓存 |
| Claude Code feature 版本固定 `1.0` | Anthropic 官方 feature，锁版本避免破坏性更新 |
| 社区 features 用 `ghcr.io/jsburckhardt/` | OpenCode 和 Codex CLI 使用同一维护者的社区 features |

### 1.3 Mounts — SSH + 持久化 Home + AI 凭证

> **注意**：mount source 必须与 [Section 0.2](#02-ai-工具认证宿主机上完成) 中凭证的实际落盘路径一致。

```jsonc
"mounts": [
    // SSH 密钥只读挂载，用于 git push
    "source=${localEnv:HOME}/.ssh,target=/home/vscode/.ssh,readonly,type=bind",
    // 持久化 home 目录，保留 shell history、工具配置
    "source=home-vscode,target=/home/vscode,type=volume",
    // OpenCode 凭证（从项目 .opencode/ 目录）
    {
        "source": "${localWorkspaceFolder}/.opencode/auth.json",
        "target": "/mnt/opencode-auth.json",
        "type": "bind"
    },
    // Codex CLI 凭证（从宿主机 ~/.codex/，需先设置 file 存储模式）
    {
        "source": "${localEnv:HOME}/.codex/auth.json",
        "target": "/mnt/codex-auth.json",
        "type": "bind"
    }
]
```

### 1.4 postCreateCommand — 对象格式

用对象格式替代单行 bash，每步有名称，便于定位失败：

```jsonc
"postCreateCommand": {
    // 写入 OpenCode 全局规则：告诉 AI 它运行在 OpenCode 环境中
    "01_write_opencode_rules": "mkdir -p /home/vscode/.config/opencode && cat > /home/vscode/.config/opencode/AGENTS.md <<'EOF'\n# Global OpenCode Rules\n\nYou are running inside **OpenCode** (https://opencode.ai), NOT Claude Code.\nEOF",
    // 安装 OpenCode antigravity-auth 插件
    "02_write_plugin_config": "mkdir -p /home/vscode/.opencode && cat > /home/vscode/.opencode/opencode.json <<'EOF'\n{\n  \"plugin\": [\"opencode-antigravity-auth@latest\"]\n}\nEOF",
    // 将挂载的 auth.json 软链接到 OpenCode 实际读取的位置
    "03_link_opencode_auth": "mkdir -p /home/vscode/.local/share/opencode && ln -sf /mnt/opencode-auth.json /home/vscode/.local/share/opencode/auth.json",
    // 将挂载的 Codex auth.json 软链接到 Codex CLI 期望的位置
    "04_link_codex_auth": "mkdir -p /home/vscode/.codex && ln -sf /mnt/codex-auth.json /home/vscode/.codex/auth.json",
    // 项目依赖安装（按项目调整）
    "05_install_deps": "npm install || echo 'deps install skipped'"
}
```

**AI 凭证挂载原理**：

> `/home/vscode` 使用了 Docker volume 持久化，这会遮盖任何直接 bind mount 到该路径下的文件。
> 因此所有凭证文件必须先挂载到中间路径 `/mnt/`，再通过 `postCreateCommand` 创建 symlink。
>
> - **OpenCode**：symlink 指向 `~/.local/share/opencode/auth.json`（不是 `~/.opencode/auth.json`），可通过 `opencode auth list` 确认
> - **Codex CLI**：symlink 指向 `~/.codex/auth.json`，可通过 `codex login status` 确认
>
> 宿主机认证步骤和凭证文件来源见 [Section 0.2](#02-ai-工具认证宿主机上完成)。

### 1.5 VS Code Extensions

```jsonc
"extensions": [
    "ms-python.python",           // 按项目需要
    "ms-python.vscode-pylance",
    "esbenp.prettier-vscode",
    "dbaeumer.vscode-eslint",
    "ms-azuretools.vscode-docker",
    "mhutchie.git-graph",
    "anthropic.claude-code"        // Claude Code VS Code 扩展
]
```

---

## 2. Subagent 选型与创建

### 2.1 选型原则

1. **按项目技术栈选择** — 不需要的 subagent 不要装（每个都占 agent 列表空间）
2. **来源**：[awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents)（MIT 协议）
3. **必须追加项目上下文** — 上游定义是通用的，需要在 system prompt 末尾追加项目特定信息
4. **code-reviewer 使用不同模型** — 跨模型对抗式审查是最佳实践
5. **security-auditor 必须只读** — 安全审计 agent 不应修改任何代码

### 2.2 常见 Subagent 菜单

根据项目技术栈从以下列表中选择：

| Subagent | 来源类别 | 适用场景 | 模型建议 |
|---|---|---|---|
| `typescript-pro` | 02-language-specialists | TypeScript 后端/全栈 | sonnet |
| `python-pro` | 02-language-specialists | Python 后端 | sonnet |
| `nextjs-developer` | 02-language-specialists | Next.js 前端 | sonnet |
| `react-specialist` | 02-language-specialists | React SPA（非 Next.js） | sonnet |
| `sql-pro` | 02-language-specialists | 数据库 schema/查询 | sonnet |
| `golang-pro` | 02-language-specialists | Go 后端 | sonnet |
| `rust-engineer` | 02-language-specialists | Rust 系统编程 | sonnet |
| `websocket-engineer` | 01-core-development | WebSocket/实时通信 | sonnet |
| `payment-integration` | 07-specialized-domains | Stripe/支付 | sonnet |
| `terraform-engineer` | 07-specialized-domains | IaC/Terraform | sonnet |
| `security-auditor` | 04-quality-security | 安全审计（**只读**） | opus |
| `code-reviewer` | 04-quality-security | 代码审查（**跨模型**） | Codex 5.3 |

### 2.3 两套 Agent 文件

建议为两个 IDE 环境各创建一套 agent 定义文件。OpenCode 和 Claude Code 的 agent frontmatter 格式不兼容
（字段名、model 格式、tools 格式都不同），无法共用同一份文件。
如果你确定只使用其中一个 IDE，可以只创建对应的一套。但建议两套都创建——
成本很低（system prompt 正文相同，只是 frontmatter 不同），且方便团队成员按偏好选择 IDE。

两种格式的差异：

#### OpenCode 格式 (`.opencode/agents/xxx.md`)

```yaml
---
description: "何时使用这个 agent 的简要说明"
mode: subagent
model: anthropic/claude-sonnet-4-5    # 支持任意 provider/model-id
tools:
  read: true
  write: true      # security-auditor 设为 false
  edit: true       # security-auditor 设为 false
  bash: true       # security-auditor 设为 false
  glob: true
  grep: true
---
```

#### Claude Code 格式 (`.claude/agents/xxx.md`)

```yaml
---
name: agent-name
description: "何时使用这个 agent 的简要说明"
tools: Read, Write, Edit, Bash, Glob, Grep    # 逗号分隔
model: sonnet                                   # 仅支持 Anthropic 别名
---
```

#### code-reviewer 的特殊处理

这是两套文件差异最大的地方：

**OpenCode** — 原生支持 Codex 模型：
```yaml
model: openai/gpt-5.3-codex    # 直接指定，零配置
tools:
  write: false
  edit: false
```

**Claude Code** — 通过 Bash 调用 Codex CLI（无需 MCP）：
```yaml
model: haiku                    # 轻量协调器
tools: Read, Glob, Grep, Bash   # Bash 用于调用 codex exec
```

subagent prompt 中指示使用 `codex exec` 非交互模式：
```bash
codex exec -m codex-5.3 -s read-only "review prompt here"
```

### 2.4 追加项目上下文

在每个 subagent 的 system prompt 末尾追加 `## 项目名称 Project Context` 段落。
关键信息包括：

- 运行时环境和约束（如 Cloudflare Workers 的 128MB 内存限制）
- 框架和库的版本
- 项目目录结构约定
- 测试框架
- 特殊的编码规范

**示例**（typescript-pro + Cloudflare Workers）：

```markdown
## MyProject Project Context - Cloudflare Workers
- Primary runtime: Cloudflare Workers (NOT Node.js)
- API framework: Hono on Workers
- Database: D1 (SQLite), bindings via env.DB
- Test framework: Vitest
- TypeScript strict mode, ESM modules only
- CRITICAL: 128MB memory limit, 30s CPU time per request
```

---

## 3. Codex CLI、Settings、MCP 与 Skills 配置

### 3.1 Codex CLI 调用方式（Claude Code 环境）

Claude Code 的 code-reviewer subagent 通过 **Bash 直接调用 Codex CLI** 的 `codex exec` 非交互模式，
不需要 MCP server 配置。这比 MCP 方式更简单、更可靠（无状态，无常驻进程）。

```bash
# code-reviewer subagent 的 prompt 中指示执行：
codex exec -m codex-5.3 -s read-only "review prompt here"

# 对于长 prompt，通过 stdin 传入：
codex exec -m codex-5.3 -s read-only - < /tmp/review-prompt.txt
```

关键参数（来自 [Codex CLI 官方文档](https://developers.openai.com/codex/cli/reference)）：

| 参数 | 值 | 作用 |
|---|---|---|
| `-m, --model` | `codex-5.3` | 指定使用 Codex 5.3 模型 |
| `-s, --sandbox` | `read-only` | 代码审查不应修改文件 |
| `PROMPT` 或 `-` | 审查内容 | `-` 表示从 stdin 读取 |

> **不要使用 `--full-auto`**：该 flag 是 `--sandbox workspace-write` 的便捷别名，
> 会覆盖 `-s read-only` 的只读约束。`codex exec` 本身就是非交互模式，无需额外 flag。
>
> **账号要求**：`-m codex-5.3` 需要 OpenAI API 账号。ChatGPT 消费者账号不支持此模型，
> 如遇 "model is not supported" 错误，请在 [platform.openai.com](https://platform.openai.com) 注册 API 账号。

> **为什么不用 MCP？** 代码审查是单轮任务，不需要 MCP 的多轮对话能力（`codex-reply` / `threadId`）。
> Bash 调用更简单：无需 `mcp.json`、无需 `settings.json` 权限白名单、无常驻进程。
> MCP 适合需要多轮交互的复杂场景（如 Agents SDK 编排的多 agent 工作流）。

### 3.2 `.claude/settings.json` — 团队共享权限（Git 追踪）

预授权项目需要的工具权限，避免每次手动确认：

```json
{
  "permissions": {
    "allow": [
      "WebFetch(domain:your-docs-domain.com)"
    ]
  }
}
```

**常见权限**：

| 权限格式 | 用途 |
|---|---|
| `WebFetch(domain:developers.cloudflare.com)` | 允许查阅 Cloudflare 文档 |
| `WebFetch(domain:hono.dev)` | 允许查阅 Hono 框架文档 |
| `WebFetch(domain:stripe.com)` | 允许查阅 Stripe 文档 |

### 3.3 `.claude/settings.local.json` — 个人本地权限（gitignore）

个人开发时需要的额外权限，不提交到 git：

```json
{
  "permissions": {
    "allow": [
      "WebFetch(domain:github.com)",
      "WebFetch(domain:developers.openai.com)"
    ]
  }
}
```

### 3.4 `.mcp.json` — MCP 服务器配置（可选）

Claude Code 通过项目根目录的 `.mcp.json` 文件配置外部 MCP（Model Context Protocol）服务器。
MCP 服务器为 AI 提供额外工具能力（如访问 Notion、Figma 等第三方服务）。

> **重要**：配置文件位于**项目根目录**（`.mcp.json`），不是 `.claude/mcp.json`。

```json
{
  "mcpServers": {
    "notion": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp.notion.com/mcp"]
    }
  }
}
```

**常见 MCP 服务器**：

| 服务 | 类型 | 说明 |
|---|---|---|
| [Notion](https://mcp.notion.com) | 远程（OAuth） | 通过 `mcp-remote` 代理，首次使用需浏览器授权 |
| [Figma](https://github.com/nichochar/figma-mcp) | 本地（API Token） | 需设置 `FIGMA_ACCESS_TOKEN` 环境变量 |
| [Cloudflare](https://github.com/cloudflare/mcp-server-cloudflare) | 本地（API Token） | Workers、D1、KV 等资源管理 |

**远程 OAuth 模式注意事项**：
- 首次连接时 `mcp-remote` 会输出授权链接，需在浏览器中完成 OAuth 登录
- Token 缓存在 `~/.mcp-auth/` 目录，后续连接自动复用
- MCP 工具在**新对话启动时**加载，修改配置后需开启新对话才能生效

> **与 Codex CLI 的区别**：MCP 服务器是常驻进程，适合需要多轮交互的外部服务集成。
> 单轮任务（如代码审查）推荐使用 Bash 直接调用（见 Section 3.1）。

### 3.5 Claude Code Skills（可选）

Skills 是 Claude Code 的可复用技能定义，通过 `/skillname` 斜杠命令显式调用。
与 subagent（由 AI 自动委派）不同，skill 由用户主动触发，适合需要精确控制调用时机的场景。

Skills 存放在 `.claude/skills/<name>/` 目录下：

```
.claude/skills/
└── codex/
    ├── SKILL.md          # 主文件（每次调用加载到上下文）
    └── reference.md      # 补充说明（通过链接按需加载）
```

**SKILL.md 格式**：

```yaml
---
name: skill-name
description: 何时使用这个 skill 的说明
argument-hint: "[参数提示]"
---

# Skill 标题

具体使用说明...
```

**设计原则**：

| 原则 | 说明 |
|---|---|
| SKILL.md 尽量精简 | 每次调用都会加载到上下文，官方上限约 500 行 |
| 说明性内容放 reference.md | 通过链接按需加载，不占用常规上下文 |
| frontmatter 仅用支持的字段 | `name`、`description`、`argument-hint` 等；当前版本不支持 `allowed-tools` |

**示例：`/codex` skill**

本项目的 `/codex` skill（`.claude/skills/codex/SKILL.md`）封装了 Codex CLI 调用的最佳实践：

- 正确的模型 ID（`-m gpt-5.3-codex`）、sandbox 模式、reasoning effort 参数
- 短 prompt 和长 prompt（stdin）两种命令模板
- 内置 `codex exec review` 和 `codex exec resume` 子命令用法
- 关键规则：禁止 `--full-auto`（与 `-s read-only` 冲突）、出错时移除 `2>/dev/null` 调试

> **与 code-reviewer subagent 的关系**：
> code-reviewer 是自动委派的 subagent，专注于代码审查场景（haiku 协调器 + Codex CLI）。
> `/codex` skill 是用户手动调用的通用技能，覆盖所有 Codex CLI 使用场景——第二意见、分析、重构建议等。
> 两者互补，不冲突。

> **注意**：Skills 是 Claude Code 专属功能，OpenCode 不支持。
> OpenCode 用户可通过其原生的 agent 体系（`model: openai/gpt-5.3-codex`）直接调用 Codex 模型。

### 3.6 `.gitignore` 条目

确保以下条目存在：

```gitignore
# OpenCode 凭证和配置
.opencode/

# Claude Code 本地设置（包含个人权限白名单）
.claude/settings.local.json
```

---

## 4. BMAD Workflow 集成（可选）

如果项目使用 [BMAD 方法论](https://github.com/bmad-code-org/bmad-method)，可以在 workflow instructions 中添加 subagent 委派指令。

### 4.1 Dev Story Workflow

在 `dev-story/instructions.xml` 的 **Step 5**（实现任务）中，在 RED PHASE 之前插入 subagent 路由块：

```xml
<!-- SUBAGENT DELEGATION - Route task to domain-specific expert -->
<action>Analyze the current task/subtask to determine its primary technology domain and
  delegate implementation to the appropriate specialist subagent:
  - [后端框架] 任务 → delegate to "[语言]-pro" subagent
  - [前端框架] 任务 → delegate to "[框架]-developer" subagent
  - [数据库] 任务 → delegate to "sql-pro" subagent
  - 简单任务（单行修改、配置调整）→ 直接实现，无需委派
</action>
```

在 **Step 6**（编写测试）中，在第一个 action 之前插入：

```xml
<action>Delegate test authoring to the same technology-domain subagent that implemented
  the task in Step 5. Provide: implementation code paths, acceptance criteria, test patterns,
  edge cases from Dev Notes.</action>
```

### 4.2 Code Review Workflow

在 `code-review/instructions.xml` 的 **Step 3** 中，在 Code Quality Deep Dive 之后插入：

```xml
<!-- CROSS-MODEL REVIEW + SPECIALIZED SUBAGENT REVIEWS -->
<action>Delegate primary code quality review to "code-reviewer" subagent
  (configured to use a DIFFERENT model for adversarial cross-model review)</action>
<action>Delegate security review to "security-auditor" subagent (read-only)</action>
<action>CONDITIONAL DOMAIN REVIEWS: only when relevant files are changed
  - 数据库变更 → "sql-pro"
  - 支付代码变更 → "payment-integration"
  - WebSocket 变更 → "websocket-engineer"
</action>
<action>Merge all subagent findings: deduplicate, preserve severity, add source attribution</action>
```

### 4.3 Dev Agent Persona

在 `agents/dev.md` 的 activation steps 中添加 subagent 意识：

```xml
<step>When implementing tasks, leverage specialized subagents for domain-specific work.
  Route tasks to the appropriate subagent by technology domain.
  For trivial tasks, implement directly.</step>
```

---

## 5. 验证清单

完成配置后，逐项验证：

### Devcontainer
- [ ] Rebuild 容器成功
- [ ] `claude --version` 可用
- [ ] `claude -p "say hi"` 能正常返回（验证 API 认证）
- [ ] `codex --version` 可用
- [ ] `opencode --version` 可用
- [ ] SSH key 可用（`ssh -T git@github.com`）

### Subagent
- [ ] `.opencode/agents/` 目录存在且包含所有 agent 文件
- [ ] `.claude/agents/` 目录存在且包含所有 agent 文件
- [ ] OpenCode 中 `opencode agent list` 显示所有 agent
- [ ] Claude Code 中 `/agents` 显示所有 agent
- [ ] code-reviewer 的 model 字段正确（OpenCode: `openai/gpt-5.3-codex`，Claude Code: `haiku` + Codex CLI）
- [ ] security-auditor 的工具权限是只读的

### OpenCode 凭证
- [ ] `opencode auth list` 显示所有已认证 provider
- [ ] 凭证路径显示为 `~/.local/share/opencode/auth.json`
- [ ] OAuth token 未过期（过期需在宿主机运行 `opencode auth login`）

### Settings + Codex CLI
- [ ] `codex --version` 可用（devcontainer feature 安装）
- [ ] `codex login status` 显示 "Logged in"
- [ ] `codex exec -s read-only "echo hello"` 能正常执行
- [ ] `.claude/settings.json` 存在且包含项目需要的 WebFetch 权限
- [ ] `.claude/settings.local.json` 在 `.gitignore` 中
- [ ] `.opencode/` 在 `.gitignore` 中

### MCP 服务器（如配置了）
- [ ] `.mcp.json` 存在于**项目根目录**（不是 `.claude/mcp.json`）
- [ ] Claude Code 新对话中能看到 MCP 工具（如 Notion 相关工具）
- [ ] 远程 OAuth 模式已完成浏览器授权（token 缓存在 `~/.mcp-auth/`）

### Skills（如配置了）
- [ ] `.claude/skills/codex/SKILL.md` 存在
- [ ] Claude Code 中输入 `/codex` 能识别并显示该 skill
- [ ] `/codex "say hello"` 能成功调用 Codex CLI 并返回结果

### 跨模型审查（端到端）
- [ ] 在 Claude Code 中调用 code-reviewer subagent，确认它能成功执行 `codex exec` 并返回审查结果

### BMAD Workflow（如适用）
- [ ] dev-story Step 5 包含 subagent 路由块
- [ ] dev-story Step 6 包含 subagent 测试委派
- [ ] code-review Step 3 包含 cross-model + security 审查
- [ ] dev.md activation 包含 subagent 意识步骤

---

## 6. 附录：文件清单模板

新项目需要创建的完整文件清单（以 7 个 subagent 为例）：

```
.devcontainer/
├── Dockerfile                          # ubuntu-24.04 + apt mirror
└── devcontainer.json                   # features + mounts + postCreateCommand

.opencode/agents/                       # OpenCode 环境
├── typescript-pro.md                   # 或其他语言 pro
├── nextjs-developer.md                 # 或其他前端框架
├── sql-pro.md
├── websocket-engineer.md               # 按需
├── payment-integration.md              # 按需
├── security-auditor.md                 # 只读，opus
└── code-reviewer.md                    # openai/gpt-5.3-codex

.claude/
├── agents/                             # Claude Code 环境（建议双轨，见 Section 2.3）
│   ├── typescript-pro.md
│   ├── nextjs-developer.md
│   ├── sql-pro.md
│   ├── websocket-engineer.md
│   ├── payment-integration.md
│   ├── security-auditor.md             # 只读，opus
│   └── code-reviewer.md               # haiku + Codex CLI 协调器
├── skills/                             # Claude Code Skills（见 Section 3.5）
│   └── codex/
│       ├── SKILL.md                    # /codex 斜杠命令定义
│       └── reference.md                # 补充说明（按需加载）
├── settings.json                       # 团队共享权限 (git tracked)
└── settings.local.json                 # 个人权限 (gitignored)

.mcp.json                               # MCP 服务器配置（见 Section 3.4）

.gitignore                              # 需包含 .opencode/ 和 .claude/settings.local.json
```

**预估配置时间**：1-2 小时（首次），后续项目复制调整约 30 分钟。

---

## 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-02-13 | 初版，基于 LaaS v2 项目实践总结 |
| v1.1 | 2026-02-13 | 补充 OpenCode auth.json symlink 细节、Codex CLI 凭证挂载（file 存储模式 + device-auth） |
| v1.2 | 2026-02-13 | 添加"如何使用本指南"段落：LLM 生成项目专属集成方案的 prompt 模板 |
| v1.3 | 2026-02-13 | 新增 Section 0 前置条件、修正 codex exec 参数、补充 apt mirror 地区提示、BMAD 前提说明、两套 agent 文件解释、验证清单增强 |
| v1.4 | 2026-02-13 | Codex 5.3 跨模型审查修正：移除 `--full-auto`（与 `-s read-only` 冲突）、补充 API 账号要求、修正 OpenCode 凭证路径并列出各平台默认路径、Claude Code 认证回退说明、统一双轨措辞、mount source 交叉引用 |
| v1.5 | 2026-02-13 | 新增 Section 3.5 Claude Code Skills：skill 目录结构、SKILL.md 格式、`/codex` skill 示例、与 subagent 的关系说明；更新验证清单和文件清单模板 |
| v1.6 | 2026-02-13 | 新增 Section 3.4 MCP 服务器配置：`.mcp.json` 正确位置（项目根目录）、远程 OAuth 模式说明、常见 MCP 服务器列表；更新验证清单和文件清单模板 |
