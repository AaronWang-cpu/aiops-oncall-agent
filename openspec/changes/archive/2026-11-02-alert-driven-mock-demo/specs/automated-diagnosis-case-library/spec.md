## MODIFIED Requirements

### Requirement: Owner-scoped diagnosis case library
系统 SHALL 提供经过身份验证的、仅返回当前 user 结构化诊断案例的列表接口；前端 AIOps 工作区 MUST NOT 再提供案例库展示入口。

#### Scenario: Owner lists cases
- **WHEN** 已认证的 user 请求诊断病例列表
- **THEN** 后端 MUST 返回该 user 的病例，按最新优先排序，并包含其任务/报告/文档链接和结构化摘要字段。

#### Scenario: Other user attempts case access
- **WHEN** 一个 user 请求属于另一个 user 的案例
- **THEN** 后端 MUST 返回统一的授权错误，不暴露案例字段或关联的工件。
