## MODIFIED Requirements

### Requirement: Live evidence-backed diagnostic progress
工作区 SHALL 按持久 SSE 展示真实阶段、工具、判断及终态，不添加虚构进展。诊断 error 后仍消费至 complete；最终成功、失败、取消由任务状态决定，而非报告或 complete 是否存在。

#### Scenario: Diagnostic phase advances
- **WHEN** 新七阶段或旧阶段进度到达
- **THEN** MUST 按序显示中文状态和后端消息，不静默过滤未知阶段。

#### Scenario: Backend invokes a tool or retrieves a source
- **WHEN** 收到 tool.call 或 reference.source
- **THEN** MUST 展示返回的生命周期/引用，可展开详情，不能推断没有提供的内容。

#### Scenario: Backend produces a report or error
- **WHEN** 收到 report、error、task.status、complete
- **THEN** MUST 保留报告及安全错误，依据最终任务状态协调证据链；error 不提前丢弃后续终态事件。

### Requirement: Centered persistent diagnostic report
中间主区域 SHALL 连续呈现诊断过程和纯 Markdown 报告，覆盖新旧阶段，终态后报告为主要阅读内容；失败有兜底报告时仍明确显示失败。

#### Scenario: Diagnosis is still running
- **WHEN** 新七阶段或历史阶段仍运行
- **THEN** MUST 显示真实进度及报告等待/生成状态，不出现无法解释的空白。

#### Scenario: Live report arrives
- **WHEN** 收到 report 而证据链尚未回载
- **THEN** MUST 立即呈现 Markdown，同时不把 task 提前改 succeeded。

#### Scenario: Persisted diagnosis is selected
- **WHEN** 历史任务已有报告
- **THEN** MUST 显示最新报告、标题和时间，保留失败/取消以及历史数据模式信息。

### Requirement: Compact AIOps execution chain presentation
右栏 SHALL 展示新七阶段及旧历史步骤、假设判断和可折叠工具，未知节点显示原名。前端摘要不回流成为推理唯一证据，MUST 保持紧凑及可追溯。

#### Scenario: Persisted steps are available
- **WHEN** 新旧持久步骤存在
- **THEN** MUST 按序显示中文标题和缩进输出，不仅过滤 planner/executor/replanner，也不展示独立大量原始 JSON 列表。

#### Scenario: Tool calls are available
- **WHEN** 存在工具审计
- **THEN** MUST 默认只显示工具名和状态，详情收起。

#### Scenario: Tool output contains structured records
- **WHEN** 结果摘要包含结构化 records
- **THEN** MUST 转成可读有限摘要，不直接以 JSON、payload 或裸 ID 充当正文；完整结果保持后端可追溯。

#### Scenario: Live tool event arrives
- **WHEN** tool.call 包含 output
- **THEN** 时间线 MUST 只展示生命周期，避免重复展示完整工具正文。

## ADDED Requirements

### Requirement: Hypotheses and incident conclusions are displayed separately
新任务 SHALL 明确展示假设状态、依据、关键缺口及事故级确认/停止原因，不将 supported 直接显示为事故根因。旧任务无这些字段不得生成占位假设或伪造判断。

#### Scenario: Hypothesis is supported but cause is unconfirmed
- **WHEN** 假设 supported 而事故 unconfirmed
- **THEN** MUST 显示“具体根因尚未确认”，root_cause 不填疑似原因。

#### Scenario: Historical assessment is no longer current
- **WHEN** 后端标记判断来自历史快照且存在未评估修改
- **THEN** MUST 区分此前判断及当前内容，不混用新解释与旧结论。

### Requirement: Visible mock and terminal-state boundaries
工作区 SHALL 显示后端提供的模拟模式、失败和取消信息，不将模拟确认表述为真实生产确认，不因程序兜底报告存在掩盖失败。

#### Scenario: Mock scenario confirms a cause
- **WHEN** 模拟场景形成有效 confirmed
- **THEN** MUST 标识模拟场景内确认，不禁止该分支，也不冒充真实事故结论。

#### Scenario: Core execution failed with a saved report
- **WHEN** 后端返回 failed 和兜底
- **THEN** MUST 同时显示失败状态与报告，不改 succeeded。

#### Scenario: New content appears on a narrow screen
- **WHEN** 窄屏展示假设、关系、工具和报告
- **THEN** MUST 保持纵向可读、无页面水平溢出，遵守既有滚动及 reduced-motion 行为。

### Requirement: Diagnostic stream replay is deduplicated
前端 SHALL 保存订阅游标并按事件 ID 去重，在断线或无 complete 的 EOF 后回载持久状态/重连，不能丢弃错误后的终态。

#### Scenario: Replayed event is received
- **WHEN** 重连收到已见报告/错误事件
- **THEN** MUST 仅显示一次，继续处理后续状态，不重新启动诊断。
