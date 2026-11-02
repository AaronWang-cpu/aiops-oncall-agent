## MODIFIED Requirements

### Requirement: Live lightweight workspace connectivity
前端 SHALL 在工作区挂载时获取轻量级后端 health，并从该结果中渲染标题栏的连接状态。

#### Scenario: Backend health succeeds
- **WHEN** 前端可以获取轻量级 `/health` 端点
- **THEN** 工作区标题 MUST 渲染连接状态，且响应 MUST 不依赖 SQLite、Milvus、配置的模型供应商或 MCP 的可用性。

#### Scenario: Backend health fails
- **WHEN** 前端无法获取成功的轻量级 health 响应
- **THEN** 工作区标题 MUST 会渲染为降级状态，但不会阻止已认证的工作区路由加载。

### Requirement: Safe configuration diagnostics
后端 SHALL 暴露了一个未经身份验证的类型化 `/config/check` 端点，该端点验证跟踪的配置并为 SQLite、Milvus、配置的模型供应商和 MCP 报告安全依赖项诊断信息。

#### Scenario: Configuration and dependencies are valid
- **WHEN** 所有需要跟踪的配置部分都已解析，且每个依赖项都可用
- **THEN** `/config/check` MUST 返回一个成功结果，标识安全的配置上下文和就绪的依赖项结果。

#### Scenario: Configuration or dependency is invalid
- **WHEN** 必需的配置部分无效，或依赖项无法访问  
- **THEN** `/config/check` MUST 返回一个非成功诊断结果，该结果标识受影响的组件，而不会序列化密钥、凭据或原始敏感配置值。
