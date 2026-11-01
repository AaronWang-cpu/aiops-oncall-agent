# aiops-evidence-chain Specification

## Purpose

定义持久化、owner 范围内的 AIOps 诊断证据、执行制品、报告来源和查询行为。

## Requirements

### Requirement: Typed diagnostic evidence is persisted
后端 SHALL 保留 owner 范围的完整脱敏日志、指标、变更、告警及已有知识引用。新调查现场证据 MUST 以 evidence_id、query_id、kind、data 四字段投影；存储元数据不得删除或混入简化业务结构，项目知识不得伪装成现场证据。

#### Scenario: Tool log evidence is stored
- **WHEN** 工具正常返回日志
- **THEN** 系统 MUST 保存完整结果、任务/步骤/调用关联和原有元信息，业务投影能通过 query_id 找到执行上下文。

#### Scenario: Knowledge evidence is stored
- **WHEN** 既有检索功能获得授权 SOP/文档引用
- **THEN** 系统 MUST 保留稳定 chunk/document/knowledgeBase 身份；直接注入的项目知识不得制造现场 evidence_id。

#### Scenario: Alert input is stored as evidence
- **WHEN** 诊断带有告警输入
- **THEN** 系统 MUST 保留 owner 范围的原始告警及来源，与工具结果证据分开。

#### Scenario: Empty or partial result is stored honestly
- **WHEN** 工具成功但结果为空，或失败前获得部分数据
- **THEN** 系统 MUST 保存已取得的完整/部分返回和原提示；空成功仍为 succeeded，失败不得包装成完整成功或假设反证。

### Requirement: Diagnostic execution steps are persisted
后端 SHALL 保存有序的新诊断阶段步骤、有效状态更新和历史判断；旧步骤保持可读。节点更新及相应下一阶段/快照 MUST 一致提交，非法输出不得产生部分有效判断。

#### Scenario: Plan and execution steps can be read
- **WHEN** 任务完成、失败或取消
- **THEN** 授权用户 MUST 能按序读取阶段、查询目的、实际调用和未满足需求，未执行计划不冒充失败调用。

### Requirement: Report provenance is durable
后端 SHALL 会保留每个最终诊断报告与该报告所使用的证据记录之间的显式链接。

#### Scenario: Report evidence is resolvable
- **WHEN** 授权调用者读取诊断报告的来源
- **THEN** 每个关联的证据 ID MUST 都必须解析为由同一 user 和诊断任务拥有的证据记录。

### Requirement: Diagnostic history and evidence chain are owner scoped
后端 SHALL 提供经过身份验证的历史记录和完整的证据链查询，可根据当前 user 过滤所有任务、步骤、审计、证据、报告、链接和 checkpoint。

#### Scenario: User lists diagnostic history
- **WHEN** 已认证的 user 请求诊断历史记录，可选时间范围
- **THEN** 后端 MUST 仅返回该 user 的任务，并按最近创建时间排序。

#### Scenario: User reads complete evidence chain
- **WHEN** 身份验证过的 user 请求他们拥有的诊断证据链
- **THEN** 后端 MUST 返回任务、输入、有序步骤、工具调用、类型化证据、报告来源和最终报告。

#### Scenario: Cross-tenant evidence access is denied
- **WHEN** 请求另一个 user 的诊断历史或证据链
- **THEN** 后端 MUST 返回统一的授权错误，不暴露诊断工件。

### Requirement: Evidence sidebar avoids duplicate report body
右侧证据链 SHALL 聚焦最终报告的来源关系、真实证据、工具调用和诊断案例，并 MUST NOT 与中间主区域重复渲染完整报告正文。

#### Scenario: Persisted report has linked evidence
- **WHEN** 选中诊断的报告关联一个或多个证据记录
- **THEN** 右侧 MUST 展示报告标题、生成时间和关联证据标识，同时将完整报告正文保留在中间主区域

#### Scenario: No report has been persisted
- **WHEN** 选中任务尚未生成报告
- **THEN** 右侧 MUST 明确显示报告尚未生成，并继续展示已经存在的证据和工具调用

### Requirement: Operator-facing evidence is an execution trace
前端 SHALL 聚焦持久执行步骤、假设判断、关系、缺口和关联工具，而不重复渲染完整报告。原始结果保留在后端，展示摘要 MUST NOT 成为模型唯一输入；历史和未知阶段不得被旧过滤器隐藏。

#### Scenario: Operator reviews the right sidebar
- **WHEN** 用户查看新任务
- **THEN** 界面 MUST 显示真实阶段、判断与可追溯工具，不能虚构步骤，不以大量裸 JSON 代替可读展示。

#### Scenario: Tool details are collapsed
- **WHEN** 用户未展开工具
- **THEN** 参数及结果 MUST 保持收起，仅显示工具名和状态。

#### Scenario: Operator expands a tool
- **WHEN** 用户展开工具
- **THEN** 界面 MUST 展示可读且有限的详情，保留完整结果可追溯性，不造成页面水平溢出。

### Requirement: Minimal diagnosis business structures
新调查 SHALL 使用六字段假设、四字段证据、七字段执行后查询、五字段关系和四字段事故结论。业务字段 MUST NOT 加入 source、coverage、locator、retry_of、评分或同义结论副本；执行层元数据保持独立。

#### Scenario: Query lifecycle is represented separately
- **WHEN** 调用计划未执行、执行中或已结束
- **THEN** 七字段查询记录 MUST 仅表示已结束的 succeeded/failed；其他状态放执行层，原始返回由证据保存。

#### Scenario: Evidence and hypothesis links resolve
- **WHEN** 假设/关系引用证据或证据引用查询
- **THEN** ID MUST 解析到同 owner、同任务的完整结果及实际调用，不允许条目级定位或跨任务引用。

### Requirement: Consistent complete assessment snapshots
有效评估 SHALL 包含全部当前假设判断、完整关系列表、事故结论和已分析证据范围，并一起保存。修改解释后当前旧关系/结论 MUST 失效，历史有效快照只表达此前判断，不覆盖当前修改。

#### Scenario: Assessment omits a hypothesis or references unknown evidence
- **WHEN** 输出遗漏/重复当前 ID 或有非法引用
- **THEN** 系统 MUST 拒绝整份更新，有限修正后仍非法则异常收尾，不先保存部分状态。

#### Scenario: Relationship becomes invalid
- **WHEN** 有效重评不再支持旧关系
- **THEN** 系统 MUST 用新完整列表替换旧列表，删除失效项，competing 不重复保存反向边。

#### Scenario: Late evidence is not analyzed
- **WHEN** 结果在最终分析范围固定后才保存
- **THEN** 系统 MUST 明确未分析，不把它静默加入有效快照，也不声称已涵盖全部证据。

### Requirement: Atomic query and report artifacts
查询终态与对应证据 SHALL 一致保存；报告、来源链接、任务/job 终态与终止事件 SHALL 一致保存并幂等补交付。成功提交前 MUST NOT 发成功终态。

#### Scenario: Database write fails halfway through a query result
- **WHEN** 证据或审计保存发生故障
- **THEN** 同次提交 MUST 回滚，不留下成功查询却无结果的半份更新，恢复不得重发原外部调用。

#### Scenario: Terminal persistence is entered twice
- **WHEN** 恢复再次处理已提交终态
- **THEN** 系统 MUST 返回既有报告及事件，不生成重复报告、链接或终止记录。
