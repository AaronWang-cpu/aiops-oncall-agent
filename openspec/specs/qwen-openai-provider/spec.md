# qwen-openai-provider Specification

## Purpose

为通过 OpenAI-compatible 协议连接到可配置模型供应商的后端 LLM 提供商合约进行定义，聊天默认使用 DeepSeek，嵌入与重排默认使用阿里云百炼，同时保持业务代码与供应商无关。

## Requirements

### Requirement: ### 需求：LangChain ChatOpenAI 提供者
后端 SHALL 使用 `langchain-openai` `ChatOpenAI` 通过 OpenAI-compatible 协议访问配置的聊天模型。

#### Scenario: 提供方使用配置值创建 ChatOpenAI
- **WHEN** 默认的 LLM 提供方创建一个聊天模型
- **THEN** 它将配置的模型、API 密钥、基础 URL、温度、超时和重试值传递给 `ChatOpenAI`。

#### Scenario: No DashScope SDK dependency
- **WHEN** 后端业务代码导入 LLM 提供者
- **THEN** 它 MUST NOT 导入 DashScope SDK 或阿里厂商私有 API。

### Requirement: ### 需求：可替换的 LLM 提供者抽象
后端 SHALL 暴露一个提供者抽象，以便不同的 OpenAI-compatible 模型提供者可以互相替换而不更改业务代码。

#### Scenario: Business code depends on abstraction
- **WHEN** 应用服务需要聊天模型访问权限
- **THEN** 它们 MUST 依赖于 LLM 提供商抽象，而不是直接构建特定提供商的客户端。

#### Scenario: 测试中可以提供提供者
- **WHEN** 测试验证模型相关的行为
- **THEN** 它们 MUST 能够在不进行网络调用的情况下提供一个假的提供者或假的聊天模型。

#### Scenario: 提供方提供 Agent 兼容的聊天模型
- **WHEN** 流式聊天服务创建一个 LangChain Agent
- **THEN** 它 MUST 通过提供方抽象获取聊天模型并将其传递给 `create_agent`。

### Requirement: LLM readiness check
后端 SHALL 提供一个模型 readiness/config 检查，用于验证配置的提供者可以访问该模型。

#### Scenario: Readiness succeeds
- **WHEN** 配置的聊天模型对最小的 health 提示做出响应
- **THEN** readiness MUST 会以提供者、模型、基础 URL 和延迟元数据报告成功，但不包含敏感信息。

#### Scenario: Readiness fails safely
- **WHEN** 模型初始化或调用失败
- **THEN** readiness MUST 报告失败时使用安全的错误信息，并且 MUST NOT 暴露 API 密钥。

### Requirement: Qwen embedding compatibility
后端 SHALL 使用原始字符串输入和配置的维度创建 OpenAI-compatible 嵌入请求，并 SHALL 使用 `embeddingBaseUrl` 与 `embeddingApiKey`（缺省分别回退到 `baseUrl` 与 `apiKey`）作为该请求的端点与凭据，使嵌入可以与聊天模型分属不同供应商。

#### Scenario: Embedding model preserves raw text inputs
- **WHEN** 默认提供程序会为 `text-embedding-v4` 创建一个嵌入模型
- **THEN** 它 MUST 会保留原始字符串或字符串数组输入以用于提供程序请求，并 MUST NOT 发送标记 ID 数组。

#### Scenario: Embedding dimensions are explicit
- **WHEN** 默认提供程序会创建一个嵌入模型
- **THEN** 它会将配置的嵌入维度传递给 OpenAI-compatible 嵌入客户端。

#### Scenario: Embedding client uses the auxiliary endpoint
- **WHEN** 默认提供程序创建一个嵌入模型
- **THEN** 该客户端 MUST 使用配置的嵌入基础 URL 与嵌入凭据，而不是聊天的基础 URL 与凭据

### Requirement: Qwen embedding batch compatibility
后端 SHALL 确保通过 OpenAI-compatible 接口发送给 `text-embedding-v4` 的每个 Embedding 请求最多包含 10 条文本，同时 MUST 为任意数量的输入返回顺序对应的完整向量集合。

#### Scenario: Small embedding input uses one compatible batch
- **WHEN** 调用方请求为不超过 10 条文本生成向量
- **THEN** Embedding 客户端 MUST 在单个不超过提供商上限的请求中处理这些文本

#### Scenario: Large embedding input is split into compatible batches
- **WHEN** 文档索引包含超过 10 个 chunk
- **THEN** Embedding 客户端 MUST 将输入拆分为每批最多 10 条的多个请求，并按输入顺序返回每个 chunk 的向量

#### Scenario: Large document indexing completes
- **WHEN** 一个可访问的文档被拆分为超过 10 个有效 chunk 且 Embedding 与 Milvus 服务可用
- **THEN** 索引任务 MUST 成功生成全部向量、写入全部 chunk 并标记为 `succeeded`

### Requirement: Configured Qwen rerank provider
LLM provider SHALL 通过项目配置创建异步文本排序能力，并使用真实阿里云百炼 `qwen3-vl-rerank` HTTP API，而不引入 DashScope SDK。重排凭据 MUST 取自 `rerankApiKey`，未配置或为空时回退到嵌入凭据，再回退到聊天凭据。

#### Scenario: Provider creates rerank client
- **WHEN** 应用装配知识检索工具
- **THEN** provider MUST 使用配置的重排凭据、rerank endpoint、模型、timeout 和 retry 创建只暴露稳定 `RerankModel` 协议的客户端

#### Scenario: Rerank response is validated
- **WHEN** 阿里云返回排序结果
- **THEN** provider MUST 校验索引和 `relevance_score`，并返回按分数降序排列且索引对应输入文档的结果

#### Scenario: Provider failure is safe
- **WHEN** rerank 请求失败、超时、限流或响应无效
- **THEN** provider MUST 在有限重试后返回不包含 API key 或上游响应敏感内容的明确错误

### Requirement: User project model capability configuration
项目 SHALL 从 `config/user.project.json` 加载 `llm.modelCapabilities`，公共 `config/project.json` SHALL NOT 重复维护该配置。用户模板 MUST 为默认聊天模型 `deepseek-flash` 提供能力档案。

#### Scenario: Merged configuration is loaded
- **WHEN** 应用加载项目配置
- **THEN** 当前聊天模型的上下文窗口能力和 rerank endpoint MUST 来自追踪的项目配置文件合并结果，而不是本机环境变量

#### Scenario: User template profiles the default chat model
- **WHEN** 检查可提交的用户配置模板
- **THEN** 它 MUST 为 `deepseek-flash` 定义 `contextWindowTokens`，且 MUST NOT 包含真实密钥

### Requirement: OpenAI-compatible chat model configuration
后端 SHALL 从 merged 项目配置中加载 OpenAI-compatible 聊天模型设置与凭据，基础配置保留通用默认值，用户配置提供每个使用者不同的模型与 API key。跟踪的默认聊天供应商 MUST 为 DeepSeek：`provider` 为 `deepseek-openai`，`baseUrl` 为 `https://api.deepseek.com/v1`，用户模板的 `chatModel` 为 `deepseek-flash` 并提供同名的上下文窗口能力档案。

#### Scenario: 跟踪的配置定义了聊天模型默认值
- **WHEN** 检查后端提供商配置文件
- **THEN** merged 配置 MUST 定义聊天供应商 `deepseek-openai`、基础 URL `https://api.deepseek.com/v1`、聊天模型 `deepseek-flash`、其上下文窗口能力档案、温度、超时与重试参数，以及开发 API 密钥

#### Scenario: Base config leaves personal model credentials empty
- **WHEN** 检查 `config/project.json`
- **THEN** `llm.apiKey`、`llm.chatModel` 和 `llm.embeddingModel` MUST 为空字符串，并由用户配置文件覆盖。

#### Scenario: Required model credentials are loaded from configuration
- **WHEN** 后端 LLM 配置是从项目配置构建的
- **THEN** 它 MUST 从 merged 项目配置文件中读取 API 键，并 MUST NOT 读取本地机器的环境变量。

#### Scenario: Runtime model options are configurable
- **WHEN** 后端 LLM 配置已构建
- **THEN** 基础 URL、模型名称、嵌入维度、温度、超时和重试参数 MUST 可配置并具有安全默认值。

#### Scenario: Missing API key is reported as configuration error
- **WHEN** merged 配置中的 API 键缺失或为空
- **THEN** 配置创建 MUST 失败，并显示不包含敏感信息的安全错误消息。

#### Scenario: Chat model requires its own capability profile
- **WHEN** merged 配置中的聊天模型没有对应的上下文窗口能力档案
- **THEN** 配置创建 MUST 失败并指出该模型名，不得回退到其他模型的能力档案。

### Requirement: Independent auxiliary endpoints for embedding and rerank
嵌入与重排 SHALL 使用可独立于聊天配置的端点与凭据，以便聊天与其他能力分属不同供应商。`llm.embeddingBaseUrl`、`llm.embeddingApiKey`、`llm.rerankApiKey` 均为可选：未设置或为空字符串时分别回退到 `llm.baseUrl`、`llm.apiKey`、`llm.embeddingApiKey`（后者自身也会回退到 `llm.apiKey`），因此未配置这些字段的运行行为 MUST 与拆分前一致。

#### Scenario: Auxiliary endpoints reuse the chat configuration by default
- **WHEN** merged 配置未设置 `embeddingBaseUrl`、`embeddingApiKey` 与 `rerankApiKey`
- **THEN** 嵌入端点 MUST 等于 `baseUrl`，嵌入凭据与重排凭据 MUST 等于 `apiKey`

#### Scenario: Auxiliary endpoints can point at another provider
- **WHEN** merged 配置把聊天放在一个供应商、把 `embeddingBaseUrl` 与 `embeddingApiKey` 指向另一个供应商
- **THEN** 嵌入请求 MUST 使用该独立端点与凭据，聊天请求 MUST 继续使用 `baseUrl` 与 `apiKey`

#### Scenario: Blank auxiliary values count as unset
- **WHEN** 辅助字段存在但为空字符串
- **THEN** 后端 MUST 按未配置处理并回退，不得把空字符串当作端点或凭据使用

#### Scenario: Non-string auxiliary value is a configuration error
- **WHEN** 辅助字段存在且不是字符串
- **THEN** 配置创建 MUST 失败并指出该字段名，不得静默回退到聊天凭据
