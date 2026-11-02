## MODIFIED Requirements

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
