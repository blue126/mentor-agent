# 用户手册编写备忘（待项目收尾统一整理）

日期: 2026-02-21  
用途: 收集当前阶段发现的“用户手册细节问题”，避免项目完工后遗漏

## 1) 文档上传相关（RAG）

- **上传大小限制是否存在**
  - 结论: Open WebUI 支持配置限制，不是固定值。
  - 关键项: `RAG_FILE_MAX_SIZE`（单文件 MB）、`RAG_FILE_MAX_COUNT`（单次上传数量）。
  - 备注: 未配置时通常等于不限（代码里为 `None`）。

- **支持的文件类型**
  - 关键项: `RAG_ALLOWED_FILE_EXTENSIONS`。
  - 手册建议: 给出推荐白名单示例（如 `pdf,docx,txt`），并说明“默认允许所有支持类型”。

- **OCR PDF（扫描件）支持**
  - 结论: 支持，但依赖文档抽取引擎是否启用 OCR。
  - 关键项: `CONTENT_EXTRACTION_ENGINE`（可选 `docling` / `mistral_ocr` / `tika` 等）。
  - Docling 关键配置: `DOCLING_PARAMS` 内的 `do_ocr`, `force_ocr`, `ocr_engine`, `ocr_lang`。
  - 手册建议: 增加“扫描 PDF 无检索结果时先检查 OCR 引擎”的排障条目。

## 2) 参考来源（编写手册时复核）

- Open WebUI 环境变量文档: `https://docs.openwebui.com/reference/env-configuration/`
- Open WebUI RAG 文档: `https://docs.openwebui.com/features/chat-conversations/rag/`
- Open WebUI 文档抽取: `https://docs.openwebui.com/features/chat-conversations/rag/document-extraction/`
- 项目测试计划: `docs/testing/plans/testing-plan-epic2.md`
- Story 2.3: `_bmad-output/implementation-artifacts/2-3-learning-plan-generator.md`
