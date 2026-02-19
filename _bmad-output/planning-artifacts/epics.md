---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
workflowCompleted: true
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/architecture.md
---

# Mentor Agent - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for Mentor Agent, decomposing the requirements from the PRD and Architecture requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

FR1: 学习计划生成器 — 根据用户上传的 PDF 文档，通过 RAG 获取目录结构，LLM 分析后生成结构化学习计划（JSON 格式），存入 SQLite
FR2: 进度追踪器 — 追踪每个 Concept 的 mastery_level (0-100) 和状态 (Not Started / In Progress / Mastered)，Quiz 答对 +10、答错 -5
FR3: 测验引擎 — 基于当前 Concept 和历史错误点，结合 RAG 检索动态生成单选题/简答题，LLM 评分并提供解析和 "Explain More" 选项
FR4: "教我" 编排器 — 处理 "Teach me X" 请求，检查前置知识→类比解释→关联 RAG 来源→关联旧知识，结构化讲解
FR5: 系统提示词策略 — 定义 Agent Persona（苏格拉底式导师），指令调优规则（前置检查、知识图谱关联、引导式纠错、RAG 限制声明）
FR6: 知识图谱 — 自动提取 Concept 间关系（Prerequisite / Related），存入 SQLite，Agent 在解释时主动引用关联节点
FR7: 文档管理 — 用户上传 PDF 到 Open WebUI，Agent 通过 RAG 反向调用 Open WebUI 检索 API 查询内容
FR8: Notion 集成 — 会话结束时自动生成学习 Summary 并推送到 Notion Database
FR9: Anki 集成 — 识别关键知识点，通过 AnkiConnect API (端口 8765) 创建闪卡，通过 AnkiWeb 同步到手机
FR10: Agent-as-LLM-Proxy — Agent Service 暴露 OpenAI 兼容 API (/v1/chat/completions)，Open WebUI 将其视为"模型"
FR11: SSE Streaming — Agent Service 以 OpenAI SSE 格式返回流式响应，Tool Use 循环期间推送中间状态（如 "Thinking..."、工具执行状态）
FR12: 前置知识检查 — 查询知识图谱检查用户是否掌握目标概念的前置节点，未掌握时建议先学习前置知识
FR13: 薄弱点补强 — 追踪特定概念的错误率和错误模式，生成针对性练习题，调度间隔重复
FR14: 上下文关联（跨文档链接）— 自动发现并提示跨书本/领域的知识关联，帮助用户构建网状知识体系

### NonFunctional Requirements

NFR1: 响应延迟 — 普通对话 < 3s，RAG 检索 < 10s，学习计划生成 < 30s（需显示进度）
NFR2: 并发 — 单用户本地使用，无高并发要求
NFR3: 资源使用 — Idle Memory < 2GB，Disk < 1GB（不含用户上传数据和 Open WebUI 数据卷）
NFR4: 可靠性 — Docker restart: unless-stopped，SQLite 每日自动备份
NFR5: 错误处理 — RAG 检索失败优雅降级为"未找到相关信息"；Notion/Anki 调用失败存入重试队列，不阻塞主流程
NFR6: 数据隐私 — 用户数据（进度、图谱、Quiz 历史）本地存储；敏感凭证通过 .env 环境变量注入，严禁硬编码
NFR7: 网络安全 — Agent Service 监听本地端口 8100，不直接暴露于公网
NFR8: 可维护性 — 模块化架构 (Routers/Services/Repositories)，关键操作详细日志，所有可配置项提取到配置文件或环境变量
NFR9: 部署 — Docker Compose 一键部署（Open WebUI + Agent Service + LiteLLM + Anki，共 4 个容器服务）

### Additional Requirements

- Starter Template: Custom FastAPI Project Structure（非标准模板，需手动初始化项目骨架 — 影响 Epic 1 Story 1）
- DB Migrations: 使用 Alembic 管理数据库迁移
- LLM Test Mocking: 使用 vcrpy 录制/回放 LLM 交互用于稳定测试
- 图谱策略: NetworkX（内存图算法）+ SQLite（持久化节点/边）混合方案
- 认证方式: Static Bearer Token（API Key），满足 OpenAI API 协议要求
- 外部集成模式: Soft Plugin / Graceful Degradation — Notion/Anki 不可用时服务继续运行
- 命名规范: 全局 snake_case（数据库表/列、API JSON key、Python 变量/函数/文件名）
- 错误处理模式: Fail Soft with Hints — 工具函数不抛异常，返回含提示信息的错误字符串给 LLM
- 异步规范: Mandatory Async/Await — 所有 I/O 必须异步，禁用 requests / time.sleep
- SSE 中间状态: Tool Status to Text Stream — 工具执行期间推送用户可见的状态文本，防止"死寂"超时
- 图谱可视化: 通过 Markdown/Mermaid 在聊天响应中生成图谱可视化

### FR Coverage Map

| FR | Epic | 描述 |
|----|------|------|
| FR1 | Epic 2 | 学习计划生成器 |
| FR2 | Epic 4 | 进度追踪器 |
| FR3 | Epic 4 | 测验引擎 |
| FR4 | Epic 3 | "教我" 编排器 |
| FR5 | Epic 1 | 系统提示词策略 |
| FR6 | Epic 2 | 知识图谱 |
| FR7 | Epic 2 | 文档管理 / RAG |
| FR8 | Epic 5 | Notion 集成 |
| FR9 | Epic 5 | Anki 集成 |
| FR10 | Epic 1 | Agent-as-LLM-Proxy |
| FR11 | Epic 1 | SSE Streaming |
| FR12 | Epic 3 | 前置知识检查 |
| FR13 | Epic 4 | 薄弱点补强 |
| FR14 | Epic 3 | 上下文关联 |

## Epic List

### Epic 1: 基础对话 — 与 AI Mentor 开始对话
用户可以通过 Open WebUI 与 Mentor Agent 进行有意义的对话。Agent 以苏格拉底式导师的身份回应，支持流式输出。包括项目骨架初始化（Custom FastAPI, Docker Compose, Alembic, 基础数据库表）、OpenAI 兼容 API、SSE Streaming、Bearer Token 认证、System Prompt 策略。
**FRs covered:** FR5, FR10, FR11

### Epic 2: 知识摄入与学习规划
用户上传 PDF 书籍后，Mentor 能够检索其内容回答问题，并自动生成结构化学习计划和知识图谱。RAG 反向调用 Open WebUI 检索 API、TOC 分析生成学习计划（JSON）、知识图谱自动提取概念间关系（NetworkX + SQLite）。
**FRs covered:** FR1, FR6, FR7

### Epic 3: 苏格拉底式教学（Teach Me）
用户说 "Teach me X"，Mentor 检查前置知识、用类比解释概念、关联 RAG 来源和旧知识，提供结构化的互动教学体验。建立在 Epic 2 的知识图谱和 RAG 能力之上，但教学功能本身独立完整。
**FRs covered:** FR4, FR12, FR14

### Epic 4: 测验评估与进度追踪
用户可以接受针对性测验，系统自动评分、追踪掌握程度、识别薄弱环节并生成补强练习。建立在前序 Epic 的概念数据之上。
**FRs covered:** FR2, FR3, FR13

### Epic 5: 外部集成（Notion & Anki）
学习会话结束后，Mentor 自动将总结推送到 Notion，关键知识点自动生成 Anki 闪卡，实现学习成果的持久化和间隔重复。Soft Plugin 模式 — Notion/Anki 不可用时优雅降级不影响核心功能。
**FRs covered:** FR8, FR9

## Implementation Strategy (来自团队讨论)

### 优先级排序
Epic 1→2→3 是**核心路径**（最快让用户感受到"这不是普通聊天机器人"的 Aha moment），Epic 4→5 是**增值功能**。

### 关键技术风险（需优先验证）
1. **LiteLLM tool_use 兼容性** — litellm-claude-code 对 Claude tool_use 格式的转译是否可靠，Epic 1 第一个 Story 就要 spike 验证
2. **Open WebUI RAG API 能力** — search_knowledge_base 反向调用的实际文档不足，Epic 2 需要实测
3. **SSE Streaming 中间状态** — sse_generator.py 在 Tool Use 循环期间推送用户可见状态文本的复杂度被低估

### 数据库演进策略
**按 Epic 迁移 schema**（Alembic migration per epic）— 每个 Epic 只建自己需要的表，按需演进，避免过早定死表结构。

### Epic 1 建议拆分策略
逐层验证：skeleton → health check → LLM proxy（无 tool）→ tool loop → SSE streaming

## Epic 1: 基础对话 — 与 AI Mentor 开始对话

用户可以通过 Open WebUI 与 Mentor Agent 进行有意义的对话。Agent 以苏格拉底式导师的身份回应，支持流式输出。

### Story 1.1: 项目骨架与开发环境初始化

As a developer,
I want a fully initialized FastAPI project skeleton with Docker Compose, Alembic, and dev tooling,
So that I have a solid foundation to build the Agent Service upon.

**Acceptance Criteria:**

**Given** 开发者克隆了代码仓库
**When** 运行 `docker compose up`
**Then** agent-service 容器启动成功，监听端口 8100
**And** `GET /health` 返回 `{"status": "ok"}`
**And** 项目目录结构符合架构文档定义（app/routers, app/services, app/repositories, app/tools, app/utils, tests/）
**And** Alembic 初始化完成，可运行 `alembic upgrade head`
**And** 首次 migration 创建基础 `users` 表（id, name, current_context, skill_level）
**And** `.env.example` 包含所有必要的环境变量模板
**And** `pyproject.toml` 包含所有生产和开发依赖
**And** 全局采用 snake_case 命名规范

### Story 1.2: OpenAI 兼容 API — 基础 LLM 代理（无 Tool）

As a user,
I want to chat with Mentor Agent through Open WebUI and receive streamed responses,
So that I can have a basic conversation experience like using any LLM.

**Acceptance Criteria:**

**Given** Agent Service 已启动且 LiteLLM 可达
**When** 客户端发送 `POST /v1/chat/completions` 请求（含 messages 数组和 Bearer Token）
**Then** Agent Service 将请求转发给 LiteLLM，获取 LLM 响应
**And** 以 OpenAI SSE 格式（`data: {"choices":[{"delta":{"content":"..."}}]}`）流式返回
**And** 无效或缺失 Bearer Token 返回 401 Unauthorized
**And** LiteLLM 不可达时返回友好错误信息（Fail Soft），不崩溃
**And** Open WebUI 配置 `http://agent-service:8100/v1` 后能正常对话
**And** Alembic migration 创建 `sessions` 表（id, user_id, started_at, ended_at, summary），用于记录会话历史

### Story 1.3: Tool Use 循环引擎

As a developer,
I want the Agent Service to maintain a complete Tool Use loop with the LLM,
So that the Agent can call tools and iterate until a final response is produced.

**Acceptance Criteria:**

**Given** Agent Service 收到一条对话请求
**When** LLM 返回 `tool_use` 指令（而非直接文本回复）
**Then** Agent Service 解析 tool_use 指令，调用对应的工具函数
**And** 工具执行结果回传给 LLM，循环继续直到 LLM 返回纯文本回复
**And** 工具函数遵循 Fail Soft with Hints 模式 — 异常不崩溃，返回错误字符串给 LLM
**And** 工具注册表（`app/tools/registry.py`）支持动态注册工具定义
**And** 至少包含一个示例工具（如 `echo`）用于验证循环完整性
**And** LiteLLM 返回的 tool_use 格式能被 Agent Service 正确解析并执行

**Implementation Note:** 需 spike 验证 litellm-claude-code 的 tool_use 格式转译兼容性（关键风险 #1）。若不兼容，备选方案为直接调用 Anthropic API。

### Story 1.4: SSE 中间状态推送

As a user,
I want to see real-time status updates during tool execution (e.g., "Thinking...", "Searching knowledge base..."),
So that I don't experience "dead air" timeouts during long tool chains.

**Acceptance Criteria:**

**Given** Agent Service 正在执行 Tool Use 循环
**When** 工具开始执行时
**Then** `sse_generator` 向客户端推送中间状态文本（如 "🔍 正在检索知识库..."）
**And** 中间状态以 OpenAI SSE delta 格式发送，Open WebUI 能正确渲染
**And** 工具执行完成后，最终回复正常流式输出
**And** 多轮工具调用时，每轮都有对应的状态更新

### Story 1.5: System Prompt 与 Mentor Persona

As a user,
I want the Agent to behave as a Socratic mentor who guides rather than just answers,
So that I have an engaging and pedagogically effective learning experience.

**Acceptance Criteria:**

**Given** 用户通过 Open WebUI 发送消息
**When** Agent Service 构建 LLM 请求时
**Then** 自动注入 System Prompt，定义导师 Persona（苏格拉底式引导、使用类比、检查前置知识）
**And** System Prompt 从配置文件加载，可修改无需改代码
**And** Prompt 指令包含：前置知识检查、知识图谱关联、引导式纠错、RAG 限制声明
**And** Agent 回复风格符合导师 Persona（引导提问而非直接给答案）

## Epic 2: 知识摄入与学习规划

用户上传 PDF 书籍后，Mentor 能够检索其内容回答问题，并自动生成结构化学习计划和知识图谱。

### Story 2.1: RAG 知识库检索工具（search_knowledge_base）

As a user,
I want the Mentor to search my uploaded PDF books when answering questions,
So that answers are grounded in my specific learning materials rather than general knowledge.

**Acceptance Criteria:**

**Given** 用户已在 Open WebUI 上传 PDF 文档
**When** Agent 调用 `search_knowledge_base` 工具（传入查询文本）
**Then** 工具通过 httpx 异步调用 Open WebUI 检索 API，返回相关文本片段
**And** 返回结果包含来源信息（文档名称、相关片段）
**And** Open WebUI API 不可达时返回友好错误字符串（Fail Soft），不中断对话
**And** 检索结果注入 LLM 上下文，Agent 回答基于检索内容
**And** 工具定义已注册到 `app/tools/registry.py`

### Story 2.2: 知识图谱数据模型与服务

As a developer,
I want a knowledge graph data layer with SQLite persistence and NetworkX in-memory algorithms,
So that concepts and their relationships can be stored, queried, and traversed efficiently.

**Acceptance Criteria:**

**Given** Alembic migration 创建了 `topics`、`concepts`、`concept_edges` 表
**When** `graph_service` 加载图谱数据时
**Then** 从 SQLite 读取节点和边，构建 NetworkX DiGraph 实例
**And** 支持添加节点（Concept: name, definition, difficulty）
**And** 支持添加边（Prerequisite / Related 关系类型）
**And** 支持查询指定 Concept 的前置节点列表
**And** 支持查询指定 Concept 的关联节点列表
**And** 图谱变更同步持久化到 SQLite
**And** 数据访问通过 `app/repositories/` 层，服务通过 `app/services/graph_service.py`

### Story 2.3: 学习计划生成器

As a user,
I want the Mentor to analyze my uploaded book and generate a structured learning plan,
So that I know what to study and in what order.

**Acceptance Criteria:**

**Given** 用户上传了 PDF 到 Open WebUI 并要求生成学习计划
**When** Agent 调用 `generate_learning_plan` 工具
**Then** 工具通过 RAG 检索文档开头/目录部分
**And** LLM 分析目录结构，提取章节 (Chapter) 和小节 (Section)
**And** 输出标准 JSON 格式：`[{chapter: "1. Intro", sections: ["1.1 Basics", "1.2 Variables"]}]`
**And** 章节和小节作为 Concept 节点存入知识图谱（调用 graph_service）
**And** 存入 SQLite `topics` 和 `concepts` 表
**And** 用户可查询 "What's next?" 获取学习计划概览

### Story 2.4: 知识图谱自动关系提取

As a user,
I want the Mentor to automatically discover relationships between concepts in my learning materials,
So that the knowledge graph reflects meaningful connections for prerequisite checking and cross-linking.

**Acceptance Criteria:**

**Given** 学习计划已生成，Concept 节点已存入图谱
**When** Agent 调用 `extract_concept_relationships` 工具
**Then** LLM 分析概念列表，识别前置关系（Concept A requires Concept B）和关联关系（Concept A relates to Concept C）
**And** 关系以边的形式存入知识图谱（graph_service.add_edge）
**And** 关系同步持久化到 SQLite `concept_edges` 表
**And** Agent 在解释概念时可主动引用关联节点（"这和你学过的 X 有关"）

## Epic 3: 苏格拉底式教学（Teach Me）

用户说 "Teach me X"，Mentor 检查前置知识、用类比解释概念、关联 RAG 来源和旧知识，提供结构化的互动教学体验。

### Story 3.1: "Teach Me" 意图识别与前置知识检查

As a user,
I want the Mentor to recognize my "Teach me X" requests and check if I have the prerequisites,
So that I'm guided to learn foundational concepts first before tackling advanced topics.

**Acceptance Criteria:**

**Given** 用户发送包含 "Teach me [concept]" 的消息
**When** LLM 决定调用 `check_prerequisites` 工具（传入目标概念名称）
**Then** 工具查询知识图谱中目标概念的前置节点
**And** 若前置概念未掌握（无 progress 记录或 mastery_level < 阈值时默认为未掌握），提示用户："你可能需要先了解 Y，是否先讲 Y？"
**And** 若前置概念已掌握（有 progress 记录且 mastery_level ≥ 阈值）或无前置要求，直接进入讲解流程
**And** Epic 4 上线前，progress 表不存在时一律视为未掌握，功能不受影响
**And** 工具注册到 `app/tools/registry.py`，逻辑在 `app/services/graph_service.py`

### Story 3.2: 类比解释与 RAG 引用讲解

As a user,
I want the Mentor to explain concepts using analogies and cite my uploaded materials,
So that I understand abstract ideas through familiar comparisons grounded in authoritative sources.

**Acceptance Criteria:**

**Given** 用户请求 Teach Me 且前置检查通过
**When** Agent 生成讲解内容时
**Then** 调用 `search_knowledge_base` 检索目标概念的相关原文片段
**And** LLM 生成包含类比的解释（如 "把 Decorator 想象成礼物的包装纸..."）
**And** 回答中引用来源信息（"From Book: Python 101, Chapter 3"）
**And** System Prompt 指令确保 Agent 使用苏格拉底式提问结尾（"基于这个理解，你觉得...？"）
**And** RAG 检索失败时，Agent 明确声明："我目前没有找到你资料中的相关内容，以下是基于通用知识的解释"

### Story 3.3: 跨文档知识关联（Contextual Linking）

As a user,
I want the Mentor to proactively link the concept being taught to things I've already learned,
So that I build a connected knowledge network instead of isolated facts.

**Acceptance Criteria:**

**Given** Agent 正在讲解一个概念
**When** Agent 调用 `get_related_concepts` 工具查询知识图谱
**Then** 返回与当前概念有 Related 关系的关联概念列表（有 progress 记录时优先展示已掌握的，无 progress 表时返回全部关联概念）
**And** Agent 在讲解中主动引用关联："记得你之前学过 [旧概念] 吗？这和当前的 [新概念] 很像，因为..."
**And** 若无关联概念，Agent 正常讲解不受影响
**And** 跨文档关联也能工作（如 Python 书中的概念关联到网络工程书中的概念）
**And** 可选用 Mermaid 语法在回复中生成概念关系图（如 `graph LR; A-->B`），展示当前概念与关联概念的关系

## Epic 4: 测验评估与进度追踪

用户可以接受针对性测验，系统自动评分、追踪掌握程度、识别薄弱环节并生成补强练习。

### Story 4.1: 测验题目动态生成

As a user,
I want the Mentor to generate quiz questions tailored to my current learning topic and weaknesses,
So that I can actively test my understanding with relevant challenges.

**Acceptance Criteria:**

**Given** 用户请求测验（如 "Quiz me on BGP" 或 "Grill me"）
**When** Agent 调用 `generate_quiz` 工具
**Then** 工具基于目标 Concept 构建提示（如有历史错误记录则结合，首次出题时无错误历史亦可正常生成）
**And** 调用 `search_knowledge_base` 检索相关段落作为出题依据
**And** LLM 生成单选题或简答题
**And** 题目难度匹配用户当前 mastery_level
**And** Alembic migration 创建 `quizzes` 表（id, user_id, session_id, concept_id, question, answer, user_answer, score, feedback, created_at）
**And** 工具注册到 `app/tools/registry.py`，逻辑在 `app/services/quiz_service.py`

### Story 4.2: 测验评分与反馈

As a user,
I want the Mentor to grade my quiz answers and provide detailed explanations,
So that I understand what I got wrong and learn from my mistakes.

**Acceptance Criteria:**

**Given** 用户提交了测验答案
**When** Agent 调用 `grade_answer` 工具
**Then** LLM 对比用户答案与标准答案，输出 JSON：`{correct: boolean, explanation: "...", related_concepts: [...]}`
**And** 若答错，提供详细解析和正确答案
**And** 提供 "Explain More" 选项，用户可深入了解相关知识点
**And** 评分结果存入 SQLite quiz 历史记录

### Story 4.3: 进度追踪与 Mastery 更新

As a user,
I want the Mentor to track my learning progress and mastery level for each concept,
So that I can see how much I've learned and what areas still need work.

**Acceptance Criteria:**

**Given** Alembic migration 创建了 `progress` 表（user_id, concept_id, mastery_level, status, error_count, last_reviewed_at）
**When** 用户完成 Teach Me 讲解时
**Then** 对应 Concept 状态更新为 "In Progress"
**When** 用户完成 Quiz 且答对时
**Then** mastery_level += 10
**When** 用户完成 Quiz 且答错时
**Then** mastery_level -= 5，error_count += 1
**And** mastery_level 达到阈值（如 80）时，状态变为 "Mastered"
**And** 用户可查询进度概览（如 "Chapter 1: 80% Completed"），以 ASCII/Markdown 进度条展示
**And** 数据访问通过 `app/repositories/progress_repo.py`

### Story 4.4: 薄弱点识别与针对性补强

As a user,
I want the Mentor to identify my weak areas and generate targeted practice,
So that I can focus my study time on concepts I struggle with most.

**Acceptance Criteria:**

**Given** 用户请求补强（如 "I need to fix my BGP path selection"）或 Agent 主动检测到薄弱点
**When** Agent 调用 `get_weak_concepts` 工具
**Then** 从 progress 表中查询 error_count 高或 mastery_level 低的概念列表
**And** Agent 针对最薄弱的概念优先生成练习题（复用 `generate_quiz`）
**And** 答对后更新 mastery_level，错误模式记录更新
**And** Agent 可主动建议："你在 MED vs Local Preference 这个点上频繁出错，要不要专门练习一下？"

## Epic 5: 外部集成（Notion & Anki）

学习会话结束后，Mentor 自动将总结推送到 Notion，关键知识点自动生成 Anki 闪卡，实现学习成果的持久化和间隔重复。Soft Plugin 模式 — 不可用时优雅降级不影响核心功能。

### Story 5.1: Notion 学习总结自动推送

As a user,
I want the Mentor to automatically generate a learning summary and push it to my Notion database after each session,
So that I have persistent, organized notes of what I learned without manual effort.

**Acceptance Criteria:**

**Given** 用户的学习会话结束（或用户明确请求总结）
**When** Agent 调用 `push_to_notion` 工具
**Then** LLM 根据会话历史生成结构化学习总结（主题、要点、掌握情况）
**And** 通过 Notion API 将总结推送到指定 Notion Database
**And** Notion Database ID 和 Token 从环境变量加载（`NOTION_TOKEN`, `NOTION_DB_ID`）
**And** Notion API 不可达时，记录日志并返回友好提示（"总结已生成但暂时无法推送到 Notion"），不阻塞对话
**And** Alembic migration 创建 `sync_queue` 表（id, target, payload, status, retry_count, created_at, last_attempted_at），用于 Notion 和 Anki 的失败重试
**And** 失败的推送存入 `sync_queue` 表，后续自动重试
**And** 应用启动时检查 `sync_queue` 中 status=pending 的记录并自动重试（基础重试机制）
**And** 外部请求超时时间为 10 秒（timeout_seconds=10）
**And** 失败重试最多 3 次（retry_max_attempts=3），采用指数退避 2s/4s/8s
**And** 达到最大重试次数后保持非阻塞，写入 `sync_queue` 由后台重试
**And** 工具注册到 `app/tools/registry.py`

### Story 5.2: Anki 闪卡自动生成与同步

As a user,
I want the Mentor to automatically create Anki flashcards for key concepts I've learned,
So that I can use spaced repetition to strengthen long-term memory retention.

**Acceptance Criteria:**

**Given** Agent 在教学或测验过程中识别出关键知识点
**When** Agent 调用 `create_anki_card` 工具
**Then** 工具构建 Anki 卡片（Front: 问题, Back: 答案/解释）
**And** 通过 AnkiConnect API（`http://anki:8765`）将卡片推送到指定 Deck
**And** AnkiConnect 不可达时，记录日志并返回友好提示，不阻塞对话
**And** 失败的卡片创建存入 `sync_queue` 表（复用 Story 5.1 创建的表），后续自动重试
**And** 外部请求超时时间为 10 秒（timeout_seconds=10）
**And** 失败重试最多 3 次（retry_max_attempts=3），采用指数退避 2s/4s/8s
**And** 达到最大重试次数后保持非阻塞，写入 `sync_queue` 由后台重试
**And** 通过 AnkiConnect 推送成功后返回确认信息（AnkiWeb 到手机的同步由 Anki 自身负责）
**And** 工具注册到 `app/tools/registry.py`
