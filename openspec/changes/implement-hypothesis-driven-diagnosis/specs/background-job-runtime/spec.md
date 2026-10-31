## MODIFIED Requirements

### Requirement: Registered background job handlers
Runtime SHALL 注册并限制 handler 的并发、超时及最大尝试次数。诊断 SHALL 采用专用一致终态交付，Runtime 不得覆盖已保存终态；其他 handler 保留原重试策略。

#### Scenario: handler 执行成功
- **WHEN** handler 正常完成
- **THEN** job MUST 保存 succeeded 与时间；若诊断已一致提交成功/失败/取消，MUST 保留该终态，不因 handler 返回再次改为成功。

#### Scenario: handler 暂时失败
- **WHEN** 普通 handler 失败且 attempt 小于最大次数
- **THEN** MUST 按原退避重排，达到上限 failed；新诊断 max_attempts=1 不因普通失败自动从头重跑。

### Requirement: Background job cancellation and retry
用户 SHALL 能取消自己的 queued/running job，并显式重试 failed/cancelled job。新诊断重试 MUST 创建新调查与新 job，保留旧任务结果；取消与终态提交需一致协调。

#### Scenario: 取消 running 任务
- **WHEN** 用户取消正在调查的诊断
- **THEN** MUST 停止新外部调用，保留已获数据，并一致保存诊断/job cancelled 及程序说明。

#### Scenario: Cancellation races terminal commit
- **WHEN** 取消和完成并发发生
- **THEN** MUST 保留先成功提交的决定，终态后不再改写，不能诊断成功而 job 取消。

#### Scenario: Explicit diagnosis retry preserves original task
- **WHEN** 用户主动重试已失败或已取消诊断
- **THEN** MUST 新建调查及关联 job，保留旧报告/状态，不在原终态任务上从头执行；其他 job 重试行为不变。

## ADDED Requirements

### Requirement: Fenced diagnostic writes and dispatch
诊断 SHALL 在提交状态及发起外部调用前验证有效租约与当前领取代次；旧执行者失租后 MUST 停止推进及写入，不能仅靠续租保护。

#### Scenario: Worker loses its lease while an external call is running
- **WHEN** 新 worker 已接管或旧租约过期
- **THEN** 旧 worker MUST 不提交结果/终态、不发起新调用；不保证已经发出的远端请求可撤销。

#### Scenario: Two workers contend for the same diagnostic job
- **WHEN** 两个 worker 并发领取/写入同一 job
- **THEN** MUST 只允许一个有效领取代次推进，拒绝另一方的状态写入，避免重复 dispatch。

### Requirement: Safe diagnostic recovery without external replay
租约恢复 SHALL 复用已提交节点、查询结果、原预算/截止时间及有效快照；未完成外部调用 MUST 不自动重放。占用发起状态未知时不返还，不伪称实际调用已确认。

#### Scenario: Completed node is recovered
- **WHEN** 服务在节点完成且提交成功后重启
- **THEN** MUST 从已保存下一阶段继续，不重新装配知识或查询已保存结果。

#### Scenario: Tool execution has an uncertain outcome
- **WHEN** 调用已预占但无法确定是否发出/完成
- **THEN** MUST 保留未知占用与中断失败说明，复用已保存部分数据，不重发、不作反证。

#### Scenario: Core model call was interrupted
- **WHEN** 有模型执行意图但没有完整有效输出提交
- **THEN** MUST 程序异常收尾，不重新调用模型；报告模型中断则直接兜底。

#### Scenario: Recovery occurs after total deadline
- **WHEN** 原总截止时间已过
- **THEN** MUST 仅程序收尾、持久化及补交付，不重新获得调查额度。

### Requirement: Atomic diagnostic job termination
诊断 SHALL 一致保存报告、来源、诊断/job 终态及有序终止事件。存储不可用时 MUST 不宣布成功，恢复时补齐而不产生重复报告或终止记录。

#### Scenario: Terminal transaction fails
- **WHEN** 报告保存成功之前或同次事务内任一步骤失败
- **THEN** MUST 回滚同次终态提交，不产生孤立成功事件或不一致任务状态。

#### Scenario: Watchdog stops execution
- **WHEN** 外层保护超时阻止正常完成
- **THEN** MUST 按执行异常保留一致状态；额外程序落盘保护不得用于延长模型或工具预算。
