# 设计：默认聊天模型切换到 DeepSeek

## 上下文

`LlmProviderConfig` 目前只有一组端点与凭据：`baseUrl` 与 `apiKey`。`build_default_llm_provider` 用它们同时创建聊天模型、嵌入客户端与重排客户端。默认供应商是百炼，三类能力恰好同源，因此这个形状长期没有暴露问题。

DeepSeek 提供 OpenAI-compatible 对话接口，但没有嵌入与重排接口。要让默认聊天模型变成 DeepSeek，同时不破坏文档索引与知识检索，端点与凭据必须可按能力拆分。

## 决策

### 1. 用三个可选字段拆分，而不是重构配置结构

考虑过的替代方案：

- **整体指向 DeepSeek**：改动最小，但嵌入与重排会请求到不存在的端点，等于把配置改成自相矛盾的静态谎言。
- **按能力分组重构配置**（`llm.chat.*`、`llm.embedding.*`、`llm.rerank.*`）：语义最清晰，但会同时破坏既有配置键、能力档案与多条需求中的字段名，代价与收益不成比例。
- **只把聊天模型改成 DeepSeek，其余沿用 `baseUrl`**：正是当前缺陷本身，不可行。

采用方案：新增 `embeddingBaseUrl`、`embeddingApiKey`、`rerankApiKey` 三个可选字段，保持既有键不动。未配置时行为与拆分前完全一致，因此对所有现存本地配置都是向后兼容的。

### 2. 回退链显式且单向

| 字段 | 未设置或为空时回退到 |
|---|---|
| `embeddingBaseUrl` | `baseUrl` |
| `embeddingApiKey` | `apiKey` |
| `rerankApiKey` | `embeddingApiKey`（其自身也会回退到 `apiKey`） |

重排的 URL 本来就有独立字段 `rerankUrl`，因此只缺凭据；重排与嵌入同属百炼能力，默认复用嵌入凭据可以少配一个字段，需要时再用 `rerankApiKey` 单独覆盖。

空字符串按「未配置」处理（与模板留空字段的约定一致），但类型错误不按未配置处理：值存在且不是字符串时直接拒绝，避免把写错的凭据静默替换成聊天凭据而定位不到问题。

### 3. 供应商实现改名

`QwenOpenAIProvider` 更名为 `OpenAICompatibleProvider`。它本身就是「可替换的 OpenAI-compatible 默认实现」，默认供应商不再是 Qwen 之后继续叫 Qwen 会持续误导。百炼专属的重排实现 `QwenVlRerankModel` 保持原名，因为它确实只对接百炼的 `qwen3-vl-rerank`。

## 风险与取舍

- **嵌入与重排仍需百炼凭据**：默认配置下聊天与嵌入分属两家供应商，使用者需要两个密钥。这是「聊天默认 DeepSeek」的直接代价，已在配置模板与文档中写明。
- **`/ready` 只探测聊天端点**：拆分后端点的可用性不会体现在 readiness 里。这是既有行为（拆分前也只探测聊天模型），本次不改。
- **本地配置不自动迁移**：使用者若已把 `baseUrl` 指向 DeepSeek，需要自行把百炼凭据填到 `embeddingApiKey`。文档给出字段表，但不做代码层迁移。

## 验证方式

- 配置层：默认值断言改向 DeepSeek；未配置辅助端点时回退到聊天值；显式配置时使用显式值；空串回退；非字符串拒绝。
- 装配层：默认嵌入客户端的 `openai_api_base` 等于 `embedding_base_url`，嵌入批次上限仍为 10。
- 端到端：用拆分后的默认配置跑通三个告警的完整诊断链路，确认聊天走 DeepSeek、诊断结论不变。
