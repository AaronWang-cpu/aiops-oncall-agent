# AIOps Diagnosis UI Specification

## Purpose

为启动真实流式Vue诊断并检查其服务器持久化报告和证据链定义经过身份验证的Vue工作区。

## Requirements

### Requirement: Authenticated AIOps diagnosis entry
前端 SHALL 提供一个经过身份验证的中文 `/aiops` 工作区，该工作区通过共享的 AIOps 合同从必需的事件查询和可选的结构化警报对象创建 API 诊断。

#### Scenario: Operator starts a diagnosis
- **WHEN** 已认证的操作员输入一个非空的诊断查询并提交表单
- **THEN** 前端 MUST 通过后端创建诊断，选择返回的任务，启动其类型的 SSE 执行流，并显示中文的准备中或运行中状态。

#### Scenario: Operator includes alert context
- **WHEN** 一个操作符提供可选的警报上下文作为 JSON 对象
- **THEN** 前端 MUST 在创建任务之前将其解析为共享请求格式。

#### Scenario: Alert context is invalid
- **WHEN** 可选的警报上下文无效 JSON 或不是对象
- **THEN** 前端 MUST 阻止提交并显示清晰的中文本地验证消息。

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

### Requirement: Diagnostic history and evidence chain
AIOps 工作区 SHALL 列出当前 user 的持久化诊断历史，并为选定任务公开完整的、由服务器支持的证据链。

#### Scenario: Operator selects a prior diagnostic
- **WHEN** 一个操作员从历史记录中选择一个诊断
- **THEN** 前端 MUST 通过后端加载其证据链，并渲染其任务状态、报告、执行步骤、工具审计、证据和源引用。

#### Scenario: Report links to evidence
- **WHEN** 选定的诊断报告包含证据链接  
- **THEN** 前端 MUST 会将报告和相应的持久化证据标识符一起显示。

#### Scenario: History request fails
- **WHEN** 一个历史或证据链请求返回标准化的后端错误
- **THEN** 前端 MUST 显示安全错误，MUST NOT 作为成功当前结果显示过时数据。

### Requirement: Responsive operational diagnosis workspace
AIOps 工作区 SHALL 保持中文事件条目、历史记录、实时进展、报告和证据控制在桌面和窄视口宽度下可读且可操作。

#### Scenario: Operator uses a narrow screen
- **WHEN** 在窄视口上显示工作区
- **THEN** 其任务控件、中文状态标签、时间线、报告和证据链 MUST 会重新布局，而不会出现水平页面溢出。

### Requirement: Professional Chinese AIOps console presentation
AIOps 工作区 SHALL 使用专业的中文 AI 运维诊断控制台布局，突出任务输入、实时诊断、证据链、最终报告和历史任务，并保持与 ChatGPT 网页式对话工作台一致的克制视觉语言。

#### Scenario: Operator opens the diagnosis workspace
- **WHEN** 已认证的 operator 打开 `/aiops`
- **THEN** 前端 MUST 显示中文的诊断输入区、实时诊断时间线、证据/报告区和历史/告警入口，并以清晰状态标签区分等待中、执行中、成功和失败。

#### Scenario: Diagnostic task is running
- **WHEN** AIOps 诊断任务正在等待、规划、执行、重规划或生成报告
- **THEN** 前端 MUST 在主工作区显示可见的运行状态，而不是只依赖按钮禁用或空白区域表达进度。

#### Scenario: Operator reviews evidence and report
- **WHEN** 一个诊断任务包含证据链、工具调用、引用或最终报告
- **THEN** 前端 MUST 将证据和报告放在可扫描的中文区域中展示，并保留来源、时间和状态信息。

#### Scenario: Responsive diagnosis workspace
- **WHEN** AIOps 工作区在窄视口中显示
- **THEN** 输入、时间线、证据、报告和历史区域 MUST 重新排列为单列或可读的纵向结构，MUST NOT 出现横向页面溢出。

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

### Requirement: Readable long-form Markdown report
最终诊断报告 SHALL 使用适合中文长文阅读的层级、间距和数据表格样式，并限制溢出范围。

#### Scenario: Report contains headings, lists and tables
- **WHEN** Markdown 报告包含多级标题、分隔线、列表、代码或表格
- **THEN** 前端 MUST 以清晰层级和足够对比度渲染内容，且表格 MUST 在自身区域滚动而不导致页面水平溢出

#### Scenario: Report is viewed on a narrow screen
- **WHEN** 报告在窄视口中展示
- **THEN** 报告正文、元数据和操作区域 MUST 纵向重排并保持可读，页面 MUST NOT 水平溢出

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

### Requirement: Long reports scroll inside the fixed diagnosis workspace
智能诊断桌面工作区 SHALL 保持受桌面视口约束的固定高度，最终报告过长时 MUST 在报告正文区域内部纵向滚动，不得继续撑高整个浏览器页面。

#### Scenario: Persisted report exceeds the available center height
- **WHEN** user 打开内容高度超过最终报告可用区域的历史诊断报告
- **THEN** AIOps 工作区外框 MUST 保持固定高度，报告标题和元信息 MUST 保持可见，Markdown 正文 MUST 提供独立纵向滚动条

#### Scenario: Other diagnosis columns contain long content
- **WHEN** 左侧历史、诊断过程或右侧执行链超过各自可用高度
- **THEN** 对应栏 MUST 在工作区内部滚动且 MUST NOT 增加页面文档高度

### Requirement: Diagnostic step and report feedback
AIOps 工作区 SHALL 允许用户评价执行步骤和最终报告，并支持附加问题说明或纠正内容。

#### Scenario: 用户评价报告
- **WHEN** 用户提交报告反馈
- **THEN** 状态 MUST 立即显示为已保存且历史任务重新打开后仍可恢复。

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
