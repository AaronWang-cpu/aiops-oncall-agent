# Automated Diagnosis Case Library Specification

## Purpose

定义自动的 owner 作用域的持久化、索引和已完成的 AIOps 诊断案例的展示。

## Requirements

### Requirement: Case knowledge indexing and retrieval traceability
已有独立案例/知识保存功能 SHALL 继续使用现有文档与持久索引流程，保留 owner、tenant 及诊断来源。新闭环成功 MUST NOT 自动触发这些功能，未确认结论不得伪装成经验证知识。

#### Scenario: Case is indexed
- **WHEN** 独立功能显式创建案例知识文档
- **THEN** MUST 保留 owner、tenant、知识分类及来源，并经标准后台索引流程处理，不在诊断请求内另建索引机制。

#### Scenario: Indexing fails
- **WHEN** 独立索引失败
- **THEN** 关联文档/任务及已有案例 MUST 保留可查询失败状态，不丢失来源。

### Requirement: Owner-scoped diagnosis case library
系统 SHALL 提供经过身份验证的、仅返回当前 user 结构化诊断案例的列表接口；前端 AIOps 工作区 MUST NOT 再提供案例库展示入口。

#### Scenario: Owner lists cases
- **WHEN** 已认证的 user 请求诊断病例列表
- **THEN** 后端 MUST 返回该 user 的病例，按最新优先排序，并包含其任务/报告/文档链接和结构化摘要字段。

#### Scenario: Other user attempts case access
- **WHEN** 一个 user 请求属于另一个 user 的案例
- **THEN** 后端 MUST 返回统一的授权错误，不暴露案例字段或关联的工件。

### Requirement: New diagnosis does not automatically create knowledge
新诊断 SHALL 只保存调查及报告；成功、失败、取消与恢复均 MUST NOT 自动创建案例、知识文档、索引任务或向量。

#### Scenario: New diagnosis succeeds
- **WHEN** 新图完成并保存报告
- **THEN** MUST 没有自动沉淀副作用，历史案例列表保持已有数据。

#### Scenario: Terminal recovery repeats
- **WHEN** 已完成诊断恢复补交付
- **THEN** MUST 不自动调用案例保存或索引，亦不删除旧案例。
