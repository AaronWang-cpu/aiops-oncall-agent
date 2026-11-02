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
AIOps 工作区 SHALL 保持中文告警条目、历史记录、实时进展、报告、证据与账本控制在桌面和窄视口宽度下可读且可操作。

#### Scenario: Operator uses a narrow screen
- **WHEN** 在窄视口上显示工作区
- **THEN** 其命令带、中文状态标签、时间线、报告、证据与账本 MUST 重新布局为纵向结构，而不会出现水平页面溢出。

### Requirement: Professional Chinese AIOps console presentation
AIOps 工作区 SHALL 围绕告警处理组织为命令带、来源列、过程列与检查器列：命令带承载诊断输入，来源列承载告警、历史与案例，过程列承载任务卡、实时过程、执行链与报告，检查器列承载结论与假设、现场证据、调查账本三个视图，并保持与工作区一致的克制视觉语言。

#### Scenario: Operator opens the diagnosis workspace
- **WHEN** 已认证的 operator 打开 `/aiops`
- **THEN** 前端 MUST 在命令带提供诊断输入与告警入口，在过程列提供实时过程与报告，在检查器列提供可切换的结论、证据与账本视图，并以清晰状态标签区分等待中、执行中、成功和失败。

#### Scenario: Operator switches inspector views
- **WHEN** operator 在结论与假设、现场证据、调查账本之间切换
- **THEN** 前端 MUST 只呈现当前视图内容，三个视图入口 MUST 始终可见，MUST NOT 因视口宽度隐藏任一视图入口。

#### Scenario: Diagnostic task is running
- **WHEN** AIOps 诊断任务正在等待、规划、执行、重规划或生成报告
- **THEN** 前端 MUST 在主工作区显示可见的运行状态，而不是只依赖按钮禁用或空白区域表达进度。

#### Scenario: Operator reviews evidence and report
- **WHEN** 一个诊断任务包含证据链、工具调用、引用或最终报告
- **THEN** 前端 MUST 将证据和报告放在可扫描的中文区域中展示，并保留来源、时间和状态信息。

#### Scenario: Responsive diagnosis workspace
- **WHEN** AIOps 工作区在窄视口中显示
- **THEN** 命令带、来源列、过程列与检查器列 MUST 重新排列为单列或可读的纵向结构，MUST NOT 出现横向页面溢出，也 MUST NOT 隐藏任何信息列。

### Requirement: Centered persistent diagnostic report
过程列 SHALL 连续呈现诊断过程和纯 Markdown 报告，覆盖新旧阶段，终态后报告为主要阅读内容；失败有兜底报告时仍明确显示失败。

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
过程列 SHALL 以可折叠区域展示新七阶段及旧历史步骤与工具调用，未知节点显示原名，并把每次工具调用与其写入的持久化证据关联起来，使 operator 能由调用直接打开证据。

#### Scenario: Persisted steps are available
- **WHEN** 新旧持久步骤存在
- **THEN** MUST 按序显示中文标题和缩进输出，不仅过滤 planner/executor/replanner，也不展示独立大量原始 JSON 列表。

#### Scenario: Tool calls are available
- **WHEN** 存在工具审计
- **THEN** MUST 默认只显示工具名和状态，展开后显示耗时、错误以及该调用写入的证据条目。

#### Scenario: Tool output contains structured records
- **WHEN** 结果摘要包含结构化 records
- **THEN** MUST 转成可读有限摘要，不直接以 JSON、payload 或裸 ID 充当正文；完整结果保持后端可追溯。

#### Scenario: Tool call wrote evidence
- **WHEN** 某次工具调用关联了持久化证据
- **THEN** MUST 以可点击条目列出这些证据，点击后 MUST 打开该证据的原始内容。

#### Scenario: Tool call wrote no evidence
- **WHEN** 某次工具调用没有关联证据且没有错误
- **THEN** MUST 明确说明本次调用没有写入证据，MUST NOT 用工具审计摘要充当证据正文。

#### Scenario: Live tool event arrives
- **WHEN** tool.call 包含 output
- **THEN** 时间线 MUST 只展示生命周期，避免重复展示完整工具正文。

### Requirement: Long reports scroll inside the fixed diagnosis workspace
智能诊断桌面工作区 SHALL 保持受桌面视口约束的固定高度，过程列的报告正文过长时 MUST 在报告正文区域内部纵向滚动，不得继续撑高整个浏览器页面。

#### Scenario: Persisted report exceeds the available center height
- **WHEN** user 打开内容高度超过报告可用区域的历史诊断报告
- **THEN** AIOps 工作区外框 MUST 保持固定高度，报告标题和元信息 MUST 保持可见，Markdown 正文 MUST 提供独立纵向滚动条

#### Scenario: Other diagnosis columns contain long content
- **WHEN** 来源列、实时过程、执行链或检查器超过各自可用高度
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

### Requirement: Evidence inspector presents persisted records
AIOps 工作区 SHALL 在检查器中按证据类型分组列出本次调查的持久化证据，并允许 operator 打开任一条查看其原始内容；原始内容 MUST 来自后端持久化记录，MUST NOT 用工具审计摘要或模型文本代替。

#### Scenario: Operator opens the evidence view
- **WHEN** 选定任务存在持久化证据
- **THEN** MUST 按类型分组列出条目，逐条显示类型、来源、摘要与时间，并标注尚未纳入结论的证据

#### Scenario: Operator opens a metric record
- **WHEN** operator 打开一条指标证据
- **THEN** MUST 展示该指标的序列名称、单位、聚合方式与点值，并保留时间与数值两列

#### Scenario: Operator opens a log or change record
- **WHEN** operator 打开一条日志或变更证据
- **THEN** MUST 展示记录中的字段与取值，MUST NOT 只显示条数

#### Scenario: Record exceeds the render budget
- **WHEN** 证据点数或记录条数超过一次渲染上限
- **THEN** MUST 明确写出总量与已显示数量，MUST NOT 静默截断

#### Scenario: Stored summary is a JSON blob
- **WHEN** 旧任务证据的摘要本身是 JSON 字符串
- **THEN** MUST 以可读标签代替该字符串充当标题，并把结构化内容交由原始内容区域呈现

#### Scenario: Hypothesis cites evidence
- **WHEN** 假设依据引用某条证据
- **THEN** 该引用 MUST 可点击并打开对应证据的原始内容

#### Scenario: Task has no evidence yet
- **WHEN** 选定任务尚未采集到证据
- **THEN** MUST 显示明确的空状态，MUST NOT 以占位证据填充

### Requirement: Diagnostic budget and query ledger
AIOps 工作区 SHALL 展示后端提供的调查额度用量与阶段截止时间，并逐条展示本次调查的查询记录及其结果，使 operator 能核对额度消耗与查询失败原因。

#### Scenario: Operator opens the ledger view
- **WHEN** 选定任务带有预算与查询记录
- **THEN** MUST 展示轮次、工具调用与内部往返的已用量与上限，以及探索、分析与总截止时间

#### Scenario: Query failed
- **WHEN** 某次查询记录为 failed
- **THEN** MUST 在条目上显示失败状态与后端给出的失败原因

#### Scenario: Operator inspects a query
- **WHEN** operator 展开某次查询的参数
- **THEN** MUST 显示该查询的工具名、问题、关联假设与调用参数

#### Scenario: Task has no query records
- **WHEN** 选定任务没有查询记录
- **THEN** MUST 显示明确的空状态，MUST NOT 伪造查询条目

#### Scenario: Budget is unavailable
- **WHEN** 选定任务尚未返回预算信息
- **THEN** MUST 说明额度信息将在诊断开始后出现，MUST NOT 显示零值用量充当真实数据
