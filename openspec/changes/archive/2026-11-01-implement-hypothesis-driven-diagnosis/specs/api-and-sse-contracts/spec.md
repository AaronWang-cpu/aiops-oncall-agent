## MODIFIED Requirements

### Requirement: AIOps execution API contract
共享契约 SHALL 定义已认证的创建、状态、报告及 SSE 订阅，保留现有路径与统一响应；新任务 MUST 暴露类型化调查结果、模式及终态，历史无新结果字段仍可读取。

#### Scenario: Diagnostic stream path is described
- **WHEN** 检查 OpenAPI
- **THEN** MUST 描述受保护的 `POST /aiops/diagnostics/{diagnosticId}:stream`、SSE 响应及可选 Last-Event-ID。

#### Scenario: Diagnostic result has evidence state
- **WHEN** 新任务响应序列化
- **THEN** MUST 保留原任务/inputPayload/resultPayload/reports 外壳，并包含假设、关系、事故结论、执行查询、现场证据、未满足需求及分析范围的类型化投影，不要求 SOP 作为必填输入。

### Requirement: AIOps graph stages use shared SSE events
共享契约 SHALL 用 task.status 表示 prepare_context、build_queries、execute_queries、revise_hypotheses、assess_hypotheses、finalize、report 的安全进度，新旧阶段保持可识别，不新增独立事件体系。

#### Scenario: Graph progress is representable
- **WHEN** 新诊断节点推进或更新判断
- **THEN** task.status MUST 表达对应阶段及安全细节；历史阶段和未知阶段不能误映射为根因已确认。

### Requirement: Diagnostic history and evidence-chain API contracts
共享契约 SHALL 保留受保护的诊断历史与证据链 API，导出新调查业务结构与 change 证据类别，保留旧告警/知识等类别及存储 DTO。

#### Scenario: History and evidence-chain paths are described
- **WHEN** 检查 OpenAPI
- **THEN** MUST 保留 `GET /aiops/diagnostics` 与 `GET /aiops/diagnostics/{diagnosticId}/evidence-chain` 及统一成功/授权错误。

#### Scenario: Evidence-chain response is typed
- **WHEN** 前后端处理证据链
- **THEN** MUST 共用任务、步骤、工具、存储证据、报告链接及安全 checkpoint 类型；新 diagnosis 投影的五类业务对象不接受多余字段，旧响应无该投影仍可解析。

## ADDED Requirements

### Requirement: Diagnostic terminal event ordering
诊断流 SHALL 持久化并按有报告时 report、失败时 error、终态 task.status、complete 的顺序交付。complete MUST 仅表示诊断流结束，成功与否由任务终态判断；聊天流语义不变。

#### Scenario: Failed diagnosis still has a fallback report
- **WHEN** 核心执行失败但程序报告已保存
- **THEN** 客户端 MUST 收到 report、error、failed task.status、complete，不因报告存在或 complete 判成功。

#### Scenario: Tool failure does not terminate investigation
- **WHEN** 一次独立工具调用失败
- **THEN** MUST 使用 tool.call failed，不发送终止级 error 来截断仍可继续的调查。

#### Scenario: Diagnosis is cancelled
- **WHEN** 用户取消生效并已保存程序说明
- **THEN** MUST 交付 cancelled task.status 和 complete，无须用执行失败 error 冒充取消。

### Requirement: Durable diagnostic stream cursor
诊断 SSE SHALL 支持基于持久事件 ID 的重连与去重，ID MUST 同时对应 SSE id 行和 JSON id。游标只允许当前用户、当前 job 的事件，订阅不得创建新的执行或临时成功事件。

#### Scenario: Reconnect resumes persisted events
- **WHEN** 客户端携带有效 Last-Event-ID 重连
- **THEN** MUST 只读取其后事件并保持顺序，不重复运行节点；客户端按 ID 去重。

#### Scenario: Cursor belongs to another job
- **WHEN** 请求带有其他用户或其他任务的游标
- **THEN** MUST 拒绝该游标并使用安全统一错误，不能透露其他任务事件。

#### Scenario: Connection ends without complete
- **WHEN** 连接断开且没有收到持久 complete
- **THEN** 客户端 MUST 回载任务或重连，不能把 EOF 自动解释为成功。

### Requirement: Diagnosis error and unconfirmed result remain distinct
新诊断契约 SHALL 区分 confirmed/unconfirmed 与任务 succeeded/failed/cancelled；未确认 root_cause MUST 为 null，stop_reason 只允许三种已定原因或 null。

#### Scenario: Budget ends before root cause confirmation
- **WHEN** 正常调查达到真实预算上限
- **THEN** MUST 表示 succeeded、unconfirmed、root_cause=null 和 budget_exhausted。

#### Scenario: Core execution fails without a stopping fact
- **WHEN** 核心模型失败且没有真实适用停止事实
- **THEN** MUST 表示 failed 与 stop_reason=null，使用统一结构化错误，不增加 execution_error 停止枚举。
