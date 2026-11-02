## MODIFIED Requirements

### Requirement: ### 需求：真实活动警报查询边界
后端 SHALL 在 real 模式从一个或多个配置的外部 Prometheus v1 或 Alertmanager v2 警报 API 中读取活动警报，而不使用伪造的备用警报或模块导入网络调用；在显式 mock 模式 MUST 直接读取配置的固定事故场景文件，把其中的告警映射为标准化活跃告警，且 MUST NOT 为此引入额外进程或第二份告警配置。每个标准化的警报 MUST 保留其源标识符和原始提供者上下文。

#### Scenario: 配置的提供者返回活跃警报
- **WHEN** 一个经过身份验证的 user 请求当前警报，并且一个或多个配置的提供者返回有效的 Alerts API 响应
- **THEN** 后端 MUST 返回规范化后的活跃警报，包括警报名称、服务、严重性、状态、开始时间、摘要、标签、注释、来源出处以及原始警报上下文。

#### Scenario: 一个配置的提供者不可用
- **WHEN** 一个配置的端点超时，返回失败响应，或返回无效响应体，而另一个配置的提供者返回有效响应
- **THEN** 后端 MUST 返回有效提供者的标准化警报，而不虚构警报数据或暴露提供者凭据。

#### Scenario: 每个配置的提供者都无法查询
- **WHEN** 每个配置的端点均超时、返回失败响应或返回无效响应正文
- **THEN** 后端 MUST 返回一个标准化的服务不可用错误，该错误不泄露凭据或生成警报数据。

#### Scenario: Mock 模式从场景提供活跃警报
- **WHEN** `aiopsDiagnosis.mode` 为 mock 且配置了有效场景文件
- **THEN** 后端 MUST 把场景中声明的告警映射为标准化活跃告警（含名称、服务、严重性、开始时间与摘要），并 MUST NOT 发起任何外部告警请求。

### Requirement: Authenticated active-alert subscription entry
前端 SHALL 会向已认证的操作员显示当前活跃告警（real 模式来自外部提供者，mock 模式来自固定场景），并提供从一条告警直接进入现有 AIOps 诊断流程的入口。

#### Scenario: Operator views active alerts
- **WHEN** 已认证的操作员打开 AIOps 工作区
- **THEN** 前端 MUST 请求活动警报 API 并显示每个返回警报的名称、服务、严重程度、状态、开始时间和摘要。

#### Scenario: Operator starts diagnosis from an alert
- **WHEN** 操作员选择一个当前警报进行诊断
- **THEN** 前端 MUST 使用该警报返回的上下文和一个标识所选警报的查询来创建并流式传输 AIOps 诊断。

#### Scenario: Alert request fails
- **WHEN** 活动警报 API 返回一个标准化的错误
- **THEN** 前端 MUST 以重试操作显示错误，并且 MUST NOT 将过时或模拟的警报显示为实时结果。

#### Scenario: Mock 模式下的告警入口
- **WHEN** mock 模式的活跃告警列表来自场景文件
- **THEN** 前端 MUST 以与 real 模式相同的列表与诊断入口展示这些告警，并从所选告警发起诊断。
