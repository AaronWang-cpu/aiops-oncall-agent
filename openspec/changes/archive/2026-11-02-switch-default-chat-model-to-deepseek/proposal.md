# 默认聊天模型切换到 DeepSeek

## Why

后端默认供应商是阿里云百炼（`provider: qwen-openai`）。实际运行使用 DeepSeek-V4.1-Flash 时，只能靠本地配置逐字段覆盖 `baseUrl`、`chatModel`、`apiKey` 与 `modelCapabilities`：仓库默认值与真实运行配置长期分叉，「默认供应商」这个字段本身失去意义，模型能力档案也需要每个使用者重复维护。

更关键的是 `apiKey` 与 `baseUrl` 同时服务聊天、嵌入与重排三类能力，而 DeepSeek 只提供对话模型、没有嵌入与重排接口。只要把 `baseUrl` 指向 DeepSeek，嵌入与重排（文档索引的向量化、知识检索的精排）就会请求到错误的端点；而只改 `chatModel` 又无法切换供应商。因此默认值变更必须同时拆开端点与凭据。

## What Changes

- 配置默认值改为 DeepSeek：`llm.provider` = `deepseek-openai`，`llm.baseUrl` = `https://api.deepseek.com/v1`；用户模板的 `llm.chatModel` = `deepseek-flash`，`llm.modelCapabilities` 提供 `deepseek-flash` 档案（上下文窗口 1048576）。
- 新增三个可选字段，把嵌入与重排的端点、凭据从聊天配置中拆出来：
  - `llm.embeddingBaseUrl`：嵌入请求的基础 URL，未设置或为空时回退 `llm.baseUrl`。
  - `llm.embeddingApiKey`：嵌入请求的凭据，未设置或为空时回退 `llm.apiKey`。
  - `llm.rerankApiKey`：重排请求的凭据，未设置或为空时回退 `llm.embeddingApiKey`。
- 默认配置据此声明：聊天走 DeepSeek，嵌入（`text-embedding-v4`）与重排（`qwen3-vl-rerank`）继续走百炼。
- `LlmProviderConfig` 增加 `embedding_base_url`、`embedding_api_key`、`rerank_api_key`；`OpenAIEmbeddings` 与 `QwenVlRerankModel` 改为使用它们。
- 上述字段存在但不是字符串时 MUST 作为配置错误拒绝，不得静默回退。
- `QwenOpenAIProvider` 更名为 `OpenAICompatibleProvider`：它提供的是可替换的 OpenAI-compatible 默认实现，重排实现 `QwenVlRerankModel` 名称不变。
- 本地未跟踪配置与演示覆盖同步到新的默认值；`config/demo.project.json` 只保留演示专用覆盖（超时预算与 mock 诊断参数），不再重复供应商字段。

## Capabilities

- `qwen-openai-provider`（默认聊天供应商改为 DeepSeek，嵌入与重排端点及凭据可独立配置）
- `runtime-readiness-checks`（readiness 依赖措辞由 Qwen 改为配置的模型供应商）
- `stream-rag-chat`（聊天模型措辞由 Qwen 改为配置的聊天模型）

## Impact

- 后端：`super_ai/llm/config.py` 的配置模型与加载、`super_ai/llm/provider.py` 的嵌入与重排装配、`super_ai/llm/__init__.py` 的导出名。
- 配置：`config/project.template.json`、`config/user.project.template.json`（可提交模板）与本地 `config/project.json`、`config/user.project.json`、`config/demo.project.json`（均被 Git 忽略）。
- 测试：默认值断言改向 DeepSeek，并补充端点评分与回退的覆盖。
- 不新增或修改任何 HTTP 端点、共享契约字段、数据库结构与前端行为；知识库索引与检索接口保持可用。

## Out of Scope

- 不移除嵌入、重排与知识库能力，也不改动它们的检索算法。
- 不引入 DeepSeek SDK 或任何厂商私有 API，仍只使用 `langchain-openai` 与独立 HTTP client。
- 不为使用者已有的本地配置做自动迁移：新增字段均为可选，未配置时行为与拆分前一致。
