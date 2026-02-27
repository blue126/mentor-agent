**MENTOR AGENT**

基于 Dify 平台的可行性分析报告

*Feasibility Analysis Report Based on Dify Platform*

网络工程与编程 AI 学习助手

作者: Vincy | 日期: 2026-02-24 | v1.0

# **目录**

# **1. 项目背景与目标**

## **1.1 项目背景**

作为网络工程师，在学习网络自动化（Nornir、NAPALM）和编程（Python、IaC）的过程中，需要一个智能学习助手提供个性化指导、知识检索和进度跟踪。当前已有基础设施包括：

* **硬件：**Dell T7910（双 E5-2686 v4、256GB RAM）+ 双 RTX 3090，Proxmox VE/ESXi
* **本地模型：**Qwen3-32B + GLM-4.7-Flash，通过 Ollama/vLLM 提供 API
* **知识库：**5 本编程书籍（27 章节）、网络工程文档、个人博客
* **进度管理：**Notion 数据库跟踪学习进度

## **1.2 核心功能需求**

|  |  |  |
| --- | --- | --- |
| **功能** | **说明** | **优先级** |
| RAG 知识检索 | 基于书籍和文档回答学习问题 | P0 必须 |
| 多轮对话教学 | 持续的教学互动，而非单次问答 | P0 必须 |
| 学习进度跟踪 | 与 Notion 数据库联动，记录学习状态 | P0 必须 |
| 长期记忆 | 跨 Session 记住学习状态、薄弱点、偏好 | P1 重要 |
| 代码执行 | 验证用户代码、演示示例 | P1 重要 |
| 自适应教学 | 根据掌握程度调整难度和内容 | P2 增强 |

# **2. Dify 平台概述**

## **2.1 什么是 Dify**

Dify 是开源 LLM 应用开发平台（GitHub 111K+ stars），提供可视化 Workflow 编排、RAG Pipeline、Agent 能力、模型管理和可观测性功能。支持 Docker 一键部署，完全运行在本地环境中。

## **2.2 Dify 核心能力**

* **Workflow Engine：**可视化拖拽工作流，支持分支/循环/条件判断，类似 Vertex ADK
* **RAG Engine：**文档上传 → 切分 → Embedding → 向量存储 → 检索，支持 PDF/Markdown
* **Model Provider：**统一接口对接 Ollama/vLLM（本地）和 DeepSeek/Gemini（API）
* **Tool Framework：**自定义 HTTP API 工具，可接入 Notion API、代码执行器等
* **Observability：**对话日志、Token 用量统计、用户反馈标注

## **2.3 与 Vertex AI Agent Builder 对比**

|  |  |  |
| --- | --- | --- |
| **维度** | **Vertex Agent Builder** | **Dify 自部署** |
| 部署方式 | Google Cloud 托管 | Docker Compose 本地 |
| 平台费用 | Agent ~$5 + Search ~$2/月 | 免费（开源） |
| 模型选择 | Gemini 为主 | 任意模型 |
| RAG | 企业级 Vertex AI Search | 内置 RAG Pipeline |
| Memory Bank | 内置长期记忆服务 | 需自行实现 |
| 数据隐私 | 数据在 Google Cloud | 100% 本地控制 |
| 离线使用 | 不支持 | 完全支持 |
| 月费用 | ~$10-20 AUD | ~$0-3 AUD |

# **3. 技术方案设计**

## **3.1 系统架构总览**

|  |  |  |
| --- | --- | --- |
| **层次** | **组件** | **技术选型** |
| 推理层 | LLM 模型 | Qwen3-32B（本地）+ DeepSeek V3.2（API 备用） |
| 应用层 | Agent 编排 | Dify Chatflow + Workflow |
| 知识层 | RAG + 记忆 | Dify Knowledge Base + Notion API |
| 基础层 | 基础设施 | Proxmox VM + Docker Compose |

## **3.2 模型路由策略**

采用双模型路由，平衡质量与成本：

|  |  |  |
| --- | --- | --- |
| **场景** | **模型** | **原因** |
| 日常学习/编程教学 | Qwen3-32B（本地） | 零成本，32B 对教学场景足够 |
| 复杂推理/长文档 | DeepSeek V3.2 API | $0.28/M，旗舰性能 |
| 记忆提取/结构化 | Qwen3-32B（本地） | 结构化输出不需旗舰模型 |

## **3.3 RAG Pipeline 设计**

**文档处理流程**

* 文档上传：通过 Dify Knowledge Base 界面上传 PDF/Markdown 格式的书籍和文档
* 文档切分：Dify 内置多种切分策略，建议初始 512 tokens/chunk，重叠 50 tokens
* Embedding：本地 bge-m3 模型（多语言支持，中英文效果优秀），通过 Ollama 提供服务
* 向量存储：Dify 默认 Weaviate，也可切换为 Qdrant/Milvus
* 检索：Hybrid Search（语义 + 关键词），top-k=5，经 Rerank 模型筛选

**知识库分组**

|  |  |  |
| --- | --- | --- |
| **知识库名称** | **内容** | **用途** |
| programming-books | 5 本编程书籍 PDF | 编程概念/语法查询 |
| network-docs | 网络自动化文档、RFC | 网络工程知识 |
| personal-notes | 个人博客、学习笔记 | 个人经验检索 |

## **3.4 长期记忆实现方案**

这是 Dify 相比 Vertex Agent Builder 的最大差距。Vertex 的 Memory Bank 基于 ACL 2025 论文，采用 Topic-based 自动提取合并记忆。在 Dify 上需自行实现，但单用户场景可简化：

**方案 A：轻量级 — Notion 状态存储（推荐初期）**

原理：对话结束后，LLM 生成结构化学习状态总结，写入 Notion 数据库。下次对话读取全部注入上下文。

流程：对话结束 → LLM 提取学习状态 → Notion API 写入 → 下次对话读取注入 System Prompt

实现难度：~50 行代码，通过 Dify Workflow 的“对话结束”触发器实现。单用户记忆量小（几十条），全量注入仅几百 tokens。

**方案 B：向量检索版（后期扩展）**

原理：将提取的记忆存入向量数据库，新对话时 Similarity Search 检索相关记忆。类似 Vertex Memory Bank 原理。

实现难度：~200-300 行代码，需 ChromaDB/Qdrant + 提取 Prompt 调优。当记忆量超过 100+ 条时再考虑升级。

## **3.5 Notion 集成方案**

通过 Dify Custom Tool 定义 HTTP API 调用 Notion API：

|  |  |  |
| --- | --- | --- |
| **操作** | **Notion API 端点** | **用途** |
| 查询进度 | POST /databases/{id}/query | 读取当前学习状态 |
| 更新进度 | PATCH /pages/{id} | 标记章节完成/更新掌握度 |
| 写入记忆 | POST /pages | 创建新的学习记忆条目 |
| 读取记忆 | POST /databases/{id}/query | 读取全部学习状态注入上下文 |

## **3.6 代码执行方案**

Dify 内置 Code Interpreter 支持 Python 和 JavaScript 执行，可在 Workflow 中作为节点使用。对于更复杂的场景（如 Nornir 脚本演示），可通过 Docker Sandbox 自行部署，通过 API 工具调用。

# **4. 部署方案**

## **4.1 基础环境**

|  |  |  |
| --- | --- | --- |
| **组件** | **规格** | **备注** |
| Proxmox VM | 4 vCPU / 16GB RAM / 100GB Disk | 运行 Dify + Weaviate + 辅助服务 |
| Ollama/vLLM | RTX 3090 #1 (24GB) | Qwen3-32B 推理服务 |
| Embedding | RTX 3090 #2 或 CPU | bge-m3 Embedding 模型 |
| 存储 | ZFS 池 | 知识库文档 + 向量数据 |

## **4.2 Docker Compose 部署**

一键部署命令：

git clone https://github.com/langgenius/dify.git && cd dify/docker && cp .env.example .env && docker compose up -d

Dify Docker 包含以下容器：dify-api、dify-web、dify-worker、postgres、redis、weaviate、nginx。启动后访问 http://localhost:80 即可使用。

## **4.3 模型配置**

1. 在 Dify → Settings → Model Provider 中添加 Ollama Provider，填入 Ollama 服务地址（如 http://192.168.1.x:11434）

2. 添加 DeepSeek API Provider 作为备用，填入 API Key

3. 在 Embedding 模型中配置 bge-m3（通过 Ollama 提供）

## **4.4 网络拓扑**

所有服务运行在内网，不需要公网暴露。客户端通过浏览器访问 Dify Web UI。DeepSeek API 是唯一的外部连接，仅在需要时调用。

# **5. 开发路线图**

## **5.1 Phase 1：MVP（1-2 周）**

目标：基本可用的 RAG 学习助手

|  |  |  |
| --- | --- | --- |
| **任务** | **工作量** | **交付物** |
| Dify Docker 部署 + 模型接入 | 0.5 天 | Dify 运行 + Qwen3-32B 对接 |
| 上传 5 本编程书籍建立知识库 | 0.5 天 | RAG Knowledge Base 可用 |
| 创建 Chatflow（System Prompt + RAG） | 1 天 | 可对话的 Mentor Agent |
| 测试 + 调优 RAG 参数 | 1-2 天 | 检索质量达标 |

## **5.2 Phase 2：Notion 集成（1-2 周）**

目标：学习进度跟踪 + 基础记忆

|  |  |  |
| --- | --- | --- |
| **任务** | **工作量** | **交付物** |
| 定义 Notion API Custom Tool | 1 天 | 查询/更新进度工具 |
| 实现学习状态提取 Workflow | 1-2 天 | 对话结束自动提取记忆 |
| 记忆注入 System Prompt 逻辑 | 0.5 天 | 跨 Session 记忆可用 |
| 端到端测试 | 1-2 天 | 学习进度 + 记忆形成闭环 |

## **5.3 Phase 3：增强功能（2-4 周）**

目标：代码执行 + 自适应教学 + 精细化

|  |  |  |
| --- | --- | --- |
| **任务** | **工作量** | **交付物** |
| Code Interpreter 集成 | 1 天 | 代码验证和演示能力 |
| 自适应难度调整逻辑 | 2-3 天 | 根据掌握度调整教学内容 |
| 多知识库路由 | 1 天 | 根据问题类型自动选择知识库 |
| 向量记忆升级（可选） | 3-5 天 | 记忆超过 100 条时切换为向量检索 |

# **6. 成本分析**

## **6.1 硬件成本**

利用现有 Homelab 硬件，无额外硬件购置。电力成本忽略不计。

## **6.2 运行成本对比**

|  |  |  |  |
| --- | --- | --- | --- |
| **方案** | **平台费** | **模型费** | **总计/月** |
| Dify + Qwen3-32B 本地 | $0 | $0 | $0 |
| Dify + DeepSeek API | $0 | ~$1-2 | ~$1-2 |
| Dify + 混合（本地为主） | $0 | ~$0.5-1 | ~$0.5-1 |
| Vertex Agent Builder | ~$5-7 | ~$5-10 | ~$10-17 |
| OpenAI API 直接使用 | $0 | ~$15-25 | ~$15-25 |

## **6.3 Token 消耗估算**

基于每天 20 轮对话的 Mentor Agent 使用场景：

|  |  |
| --- | --- |
| **指标** | **估算值** |
| 单轮 Input tokens | ~300-500（含 RAG 上下文约 2000） |
| 单轮 Output tokens | ~300-800 |
| 20 轮累计（含历史） | ~100-150K tokens |
| 每月消耗 | ~3-4.5M tokens |
| DeepSeek V3.2 月费用 | ~$1.5 AUD |

# **7. 风险评估与应对**

|  |  |  |  |
| --- | --- | --- | --- |
| **风险** | **影响** | **概率** | **应对措施** |
| RAG 检索质量不达标 | 高 | 中 | 调优 chunk 大小、加 Rerank、手动标注辅助 |
| 记忆提取不准确 | 中 | 中 | Prompt 迭代调优、定期人工校验 Notion 数据 |
| Qwen3-32B 教学质量不足 | 中 | 低 | 切换到 DeepSeek API、等更强的开源模型 |
| Dify 平台 Bug | 低 | 低 | 活跃社区支持、可降级版本 |
| Proxmox VM 资源不足 | 低 | 低 | 现有 256GB RAM 富余大 |

# **8. 可行性结论**

## **8.1 总体评估**

基于以上分析，使用 Dify 平台开发 Mentor Agent 的可行性评估如下：

|  |  |  |
| --- | --- | --- |
| **维度** | **评估** | **说明** |
| 技术可行性 | ★★★★☆ 很高 | Dify 内置 RAG/Workflow/Tool 覆盖 90% 需求 |
| 成本可行性 | ★★★★★ 极高 | 几乎零成本运行，远低于任何云方案 |
| 开发难度 | ★★★☆☆ 中等 | 可视化编排降低门槛，记忆系统需自建 |
| 扩展性 | ★★★★☆ 很高 | 模型可替换、知识库可扩展、Workflow 可迭代 |
| 数据隐私 | ★★★★★ 极高 | 书籍和学习数据 100% 本地 |

## **8.2 推荐策略**

**立即开始：**Phase 1 MVP 只需 1-2 天即可产出可用的 RAG 学习助手，强烈建议先动手，在实践中迭代。

**混合模型：**日常使用 Qwen3-32B 本地推理，复杂任务调用 DeepSeek V3.2 API，月费用 < $2。

**记忆优先 Notion：**初期用方案 A（Notion 状态存储），简单有效。当记忆超过 100+ 条时再升级向量检索。

**保留 Vertex 期权：**可用 Google $300 免费额度快速验证 Memory Bank 效果，作为 Dify 自建记忆的参考基准。

## **8.3 最终结论**

**可行性结论：强烈推荐。**Dify + Qwen3-32B + Notion 的组合能够满足 Mentor Agent 的核心需求，以接近零成本实现 Vertex Agent Builder 80-90% 的能力。唯一的差距（长期记忆）可通过简单的 Notion 集成弥补。建议立即启动 Phase 1 MVP。