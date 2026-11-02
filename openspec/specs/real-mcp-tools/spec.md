# real-mcp-tools Specification

## Purpose

为本地官方 MCP 服务器定义实际的 MCP 集成边界，包括发现、调用、故障处理、readiness 和审计行为。

## Requirements

### Requirement: Real MCP SSE tools
真实模式 SHALL 通过当前用户启用的受管理连接发现真实工具，用户未配置连接时保留既有项目 CLS 回退规则。显式 Mock 诊断使用独立模拟工具，不得影响聊天或真实连接的定义、权限及结果。

#### Scenario: Agent loads managed tools
- **WHEN** 用户启动聊天或真实 AIOps
- **THEN** MUST 只加载该用户授权连接或既有合法 CLS 配置真实发现的工具，不把模拟指标/变更当成真实能力。

### Requirement: MCP calls are audited
每个 MCP 工具调用 SHALL 都会使用现有的工具调用审计生命周期，包括工具名称、参数、结果摘要、持续时间、状态和错误信息。

#### Scenario: MCP call completes
- **WHEN** 一个 Agent 调用发现的 MCP 工具
- **THEN** 相应的聊天工具审计 MUST 应完成或失败，并具有真实的 MCP 结果。

### Requirement: Real MCP tools are available to AIOps execution
真实诊断 SHALL 按实际工具定义执行并审计请求，诊断专用客户端包括发现在内 MUST 禁止自动重试。失败不伪造证据，不自动阻断独立查询；聊天与连接管理检查保留原策略。

#### Scenario: MCP execution failure is surfaced
- **WHEN** 诊断 MCP 首次请求失败
- **THEN** MUST 记录明确失败，底层实际请求不自动重复，最终任务状态由整体调查结果决定而不是一次工具失败。

#### Scenario: Existing connection settings are preserved
- **WHEN** 诊断覆盖 retries=0 及阶段超时
- **THEN** MUST 不修改用户保存的连接配置或共享聊天客户端。

### Requirement: MCP server credentials use merged project configuration
本地 CLS MCP Server 启动和后端 MCP 配置检查 SHALL 从 merged 项目配置读取 CLS 凭据和连接参数。

#### Scenario: Base config leaves personal MCP credentials empty
- **WHEN** 检查 `config/project.json`
- **THEN** `clsMcpServer.secretId` 和 `clsMcpServer.secretKey` MUST 为空字符串，并由用户配置文件覆盖。

#### Scenario: Local startup receives merged MCP credentials
- **WHEN** 使用本地启动脚本启动 CLS MCP Server
- **THEN** 脚本 MUST 从 merged 项目配置导出 `TENCENTCLOUD_SECRET_ID`、`TENCENTCLOUD_SECRET_KEY`、`TRANSPORT`、`PORT` 和 `TZ`。

### Requirement: Explicit isolated mock diagnosis tools
Mock 诊断 SHALL 由显式配置启用并固定单事故快照，该快照 MUST 以告警列表声明至少一条告警（各含名称、服务、实例、严重性、开始时间与摘要），同一快照中的多条告警 MUST 指向同一组事实；日志、指标及变更只筛选已有场景数据。真实模式 MUST NOT 因失败回退 Mock，未知能力不得临时编造结果。

#### Scenario: Query window changes within one scenario
- **WHEN** 对同一场景改变时间窗口补查
- **THEN** MUST 筛选同一时间线，不随窗口移动指标峰值、变更或告警时间。

#### Scenario: Unsupported mock query is submitted
- **WHEN** Mock 不支持某查询参数/语法或所需数据
- **THEN** MUST 返回明确失败、空结果或能力缺口，不忽略约束返回虚构匹配。

#### Scenario: Real metric or change tool is missing
- **WHEN** 真实诊断没有已接入的指标/变更工具
- **THEN** MUST 如实反馈能力缺口，不能调用本地模拟结果冒充真实观测。

#### Scenario: Scenario is supplied to diagnosis
- **WHEN** 场景工具向模型返回数据
- **THEN** MUST 只提供事实快照与查询结果，不包含预设根因、评分或评测答案，任务/报告明确模拟性质。

#### Scenario: Scenario declares the alerts offered to the operator
- **WHEN** 读取固定的 mock 场景快照
- **THEN** MUST 接受一条或多条告警声明（至少一条），每条含名称、服务、实例、严重性与开始时间；空告警列表 MUST 作为非法快照被拒绝。

### Requirement: Diagnostic call failure and correction boundaries
诊断 SHALL 禁止 SDK、MCP 及任务层自动重复失败调用；合法的模型输出修正最多一次且自身也无自动重试。重复相同失败参数不得仅换 ID 冒充补查。

#### Scenario: Invalid model output is corrected once
- **WHEN** 模型接口成功但返回非法结构
- **THEN** MUST 携原输出与校验错误最多修正一次，修正失败后程序异常收尾。

#### Scenario: Evidence gap warrants a new query
- **WHEN** 新事实或新的数据条件要求补查
- **THEN** MUST 说明新信息价值，并作为新实际调用占预算，不产生工具重试关联。
