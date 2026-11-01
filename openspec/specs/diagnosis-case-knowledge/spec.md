# Diagnosis Case Knowledge Specification

## Purpose

将已完成的、有证据支持的 AIOps 报告明确保留为 user 拥有的可索引知识文档。

## Requirements

### Requirement: Save completed diagnostic as user-scoped knowledge case
系统 SHALL 保留 owner 对已完成报告的独立显式知识保存入口及历史案例访问，新诊断成功不得自动入库。保存 MUST 沿用标准文档/索引流程及现有来源，不将未确认判断包装成已验证根因。

#### Scenario: Successful report becomes a case
- **WHEN** owner 显式保存成功任务的已有报告
- **THEN** MUST 沿用独立知识保存流程保留任务、报告和证据来源，不仅因为诊断 reached succeeded 自动触发保存。

#### Scenario: Non-owner cannot access a case
- **WHEN** 用户请求其他 owner 的案例或保存其报告
- **THEN** MUST 返回统一授权错误，不暴露案例、文档、报告或任务。

#### Scenario: Case persistence repeats
- **WHEN** 相同已有案例再次处理或显式内容重复保存
- **THEN** MUST 沿用已有幂等或内容冲突语义，不重复创建同一案例文档/索引任务。
