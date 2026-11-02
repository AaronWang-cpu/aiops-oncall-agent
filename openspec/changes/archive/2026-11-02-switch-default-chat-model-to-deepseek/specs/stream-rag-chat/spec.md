## MODIFIED Requirements

### Requirement: Agent-driven streaming chat
后端 SHALL 进程通过配置的 LangChain `create_agent` Agent 使用配置的聊天模型和可用的 LangChain 工具进行认证聊天。

#### Scenario: Chat uses configured Agent
- **WHEN** 已认证的 user 向聊天会话发送聊天消息
- **THEN** 后端 MUST 调用从配置的 LLM 提供商和可用聊天工具创建的 Agent

#### Scenario: No custom LangGraph for ordinary chat
- **WHEN** 普通聊天已实现
- **THEN** 后端 MUST NOT 为聊天对话流程使用自定义的 LangGraph 状态图。

#### Scenario: Model chooses tool use
- **WHEN** 的 user 发送一条可能需要或不需要知识上下文的消息
- **THEN** 的后端 MUST 让模型决定是否调用知识检索工具，而不是作为无条件的预步骤执行检索。
