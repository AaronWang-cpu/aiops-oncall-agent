## REMOVED Requirements

### Requirement: Automatic structured diagnosis case persistence
**Reason**：用户确认新闭环不自动写入案例或知识库，本期不扩展案例沉淀。
**Migration**：保留既有历史案例、owner 查询与独立保存能力；新诊断不注入自动沉淀步骤，不删除已有文档、索引任务或向量。

## MODIFIED Requirements

### Requirement: Case knowledge indexing and retrieval traceability
已有独立案例/知识保存功能 SHALL 继续使用现有文档与持久索引流程，保留 owner、tenant 及诊断来源。新闭环成功 MUST NOT 自动触发这些功能，未确认结论不得伪装成经验证知识。

#### Scenario: Case is indexed
- **WHEN** 独立功能显式创建案例知识文档
- **THEN** MUST 保留 owner、tenant、知识分类及来源，并经标准后台索引流程处理，不在诊断请求内另建索引机制。

#### Scenario: Indexing fails
- **WHEN** 独立索引失败
- **THEN** 关联文档/任务及已有案例 MUST 保留可查询失败状态，不丢失来源。

## ADDED Requirements

### Requirement: New diagnosis does not automatically create knowledge
新诊断 SHALL 只保存调查及报告；成功、失败、取消与恢复均 MUST NOT 自动创建案例、知识文档、索引任务或向量。

#### Scenario: New diagnosis succeeds
- **WHEN** 新图完成并保存报告
- **THEN** MUST 没有自动沉淀副作用，历史案例列表保持已有数据。

#### Scenario: Terminal recovery repeats
- **WHEN** 已完成诊断恢复补交付
- **THEN** MUST 不自动调用案例保存或索引，亦不删除旧案例。
