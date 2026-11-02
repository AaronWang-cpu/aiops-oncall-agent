# 任务：默认聊天模型切换到 DeepSeek

## P1 后端：拆分配置模型与装配

- [x] `LlmProviderConfig` 增加 `embedding_base_url`、`embedding_api_key`、`rerank_api_key`
- [x] `load_llm_provider_config` 读取 `embeddingBaseUrl`、`embeddingApiKey`、`rerankApiKey` 并实现回退链
- [x] 值存在但非字符串时按配置错误拒绝
- [x] `OpenAIEmbeddings` 改用 `embedding_base_url` 与 `embedding_api_key`
- [x] `QwenVlRerankModel` 改用 `rerank_api_key`
- [x] `QwenOpenAIProvider` 更名为 `OpenAICompatibleProvider`，同步 `llm/__init__.py` 导出

## P2 配置：默认值与模板

- [x] `config/project.template.json`：`provider`、`baseUrl` 改为 DeepSeek，新增空的 `embeddingApiKey`、`rerankApiKey` 与百炼 `embeddingBaseUrl`
- [x] `config/user.project.template.json`：`chatModel` 改为 `deepseek-flash`，能力档案改为 `deepseek-flash`（1048576）
- [x] 本地 `config/project.json`、`config/user.project.json` 同步为 DeepSeek 聊天 + 百炼嵌入/重排凭据
- [x] `config/demo.project.json` 收敛为只保留演示专用覆盖

## P3 测试

- [x] 默认值断言改向 DeepSeek（供应商、基础 URL、聊天模型、能力档案）
- [x] 断言默认配置下嵌入端点与凭据独立于聊天端点与凭据
- [x] 新增未配置回退、显式覆盖、空串回退、非字符串拒绝的覆盖
- [x] 断言默认嵌入客户端的 `openai_api_base` 使用嵌入端点
- [x] 模板与忽略规则断言补充新增凭据字段

## P4 规格与文档

- [x] 新建并校验 OpenSpec 变更，归档后同步主规格
- [x] 后端 README、仓库 README、配置教程、平台安装文档与 AGENTS 措辞同步
- [x] 架构图脚本中的供应商标签同步

## P5 验证

- [x] 后端全量 pytest（仅保留本机无 `/bin/bash` 的既知环境失败）
- [x] `uv run ruff check .`、`uv run pyright` 与本机基线一致
- [x] `openspec validate --all`、`npm run docs:build` 通过
- [x] 用新默认配置复验三个告警的完整诊断链路
