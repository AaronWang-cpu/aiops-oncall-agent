## MODIFIED Requirements

### Requirement: Plan-Execute-Replan diagnostic graph
后端 SHALL 为新的已认证 AIOps 任务执行具备 prepare_context、build_queries、execute_queries、revise_hypotheses、assess_hypotheses、finalize 和 report 阶段的假设驱动调查，先采证再生成初始假设，并依据有效评估选择后续操作。旧历史任务 MUST 保持可读。

#### Scenario: Diagnostic follows the graph lifecycle
- **WHEN** 已认证用户启动新诊断
- **THEN** 系统 MUST 持久化运行状态，先构建并执行查询，再依据实际结果生成及评估假设，最终经程序收尾交付报告。

#### Scenario: Replanner continues only when warranted
- **WHEN** 有效评估需要补充事实、细化解释或结束
- **THEN** 系统 MUST 分别选择构建查询、增量修改假设或收尾，不用命中规则代替因果判断。

### Requirement: Evidence-based execution and reporting
诊断 SHALL 只调用当前模式中合法可用的工具；真实模式 MUST 使用真实启用连接，显式 Mock 模式 MUST 标记模拟场景。根因确认由证据评估完成，报告 MUST 表达已有判断，不能首次生成原因或以知识默认值填补事故事实。

#### Scenario: Real MCP evidence is used
- **WHEN** 真实诊断调用 CLS MCP 工具
- **THEN** 系统 MUST 保存实际返回或明确失败，不因失败回退到模拟数据。

#### Scenario: 不支持的证据无法得出结论
- **WHEN** 对某原因没有支持必要因果环节的现场证据
- **THEN** 报告 MUST 明确未验证，不得把工具成功、变更命中或知识默认配置作为根因确认。

### Requirement: Diagnostic persistence and ownership
后端 SHALL 通过 owner 范围的存储库保留当前调查、有效判断、执行记录、checkpoint、报告和审计，并一致保存诊断任务与后台 job 终态。

#### Scenario: Diagnostic artifacts are owner scoped
- **WHEN** 用户读取或流式订阅诊断
- **THEN** 系统 MUST 仅公开该用户拥有的任务及安全工件，跨用户访问返回统一授权错误。

#### Scenario: Terminal task is persisted
- **WHEN** 诊断成功、失败或取消
- **THEN** 系统 MUST 一致保存任务/job 状态、结果、完成时间、可生成的报告与终止事件，保存失败不得先宣布成功。

### Requirement: Diagnostic SSE lifecycle
诊断 SHALL 在持久后台任务中执行，并先保存进度与终止事件再交付。单次工具错误 MUST NOT 自动终止其他独立查询或整次调查。

#### Scenario: Diagnostic stream disconnects
- **WHEN** 用户关闭或刷新页面
- **THEN** 诊断 MUST 继续执行，重新订阅能够恢复已保存事件、终态及证据链，不重新运行已执行调查。

### Requirement: Diagnostic workflow writes evidence-chain records
诊断阶段 SHALL 持续保留有序步骤、完整脱敏工具结果、查询上下文和有效评估的来源信息；摘要 MUST NOT 成为推理的唯一证据。

#### Scenario: Workflow persists node artifacts
- **WHEN** 一个诊断阶段有效完成
- **THEN** 系统 MUST 保存相应步骤、更新及下一阶段；评估成功时同次保存一致判断快照。

### Requirement: Structured Chinese alert analysis report
诊断 SHALL 交付纯中文 Markdown 报告，以诊断结论、原因与证据、调查结果与局限、后续建议四部分组织。程序 MUST 固定结论头部，模型只表达已有分析；无有效判断时仅报告事实和局限。

#### Scenario: Evidence supports one or more active alerts
- **WHEN** 收到告警及有效分析
- **THEN** 报告 MUST 说明具体根因是否确认、因果依据、主要候选及建议前提，不首次补齐未验证因果链。

#### Scenario: Evidence is missing or a tool fails
- **WHEN** 告警字段、知识或工具数据缺失/失败
- **THEN** 报告 MUST 明确未获取、证据不足或失败原因，不编造告警、日志、原因或已执行处置。

#### Scenario: Report model invocation fails
- **WHEN** 报告模型失败、输出为空或无效
- **THEN** 系统 MUST 保存程序 Markdown 兜底，不额外修正，不仅因报告失败改变已有效的诊断结论。

#### Scenario: Report output remains plain Markdown
- **WHEN** 报告交付
- **THEN** 持久内容和 report 事件 MUST 是纯 Markdown，不是 JSON 报告对象或包裹全文的代码围栏。

#### Scenario: Historical assessment is used after a failed reassessment
- **WHEN** 新解释或证据未完成评估而仅有历史有效快照
- **THEN** 报告 MUST 明确此前判断与未分析内容，不把旧 supported 或 confirmed 移植到修改后的解释。

## REMOVED Requirements

### Requirement: SOP-first diagnostic planning
**Reason**：用户已确认新诊断以告警、固定项目知识与现场采证启动，不再要求额外 SOP 检索。
**Migration**：保留历史 SOP 记录、已有检索能力及可选背景输入；无 SOP 不再自动标为退化流程，不删除独立知识库功能。

## ADDED Requirements

### Requirement: Hypothesis assessment and root cause confirmation
诊断 SHALL 完整更新全部当前假设及关系，分别判断假设状态、事故级确认和下一动作。确认 MUST 同时具备具体原因、因果链证据、无关键反证或主要未决竞争解释；不得以数值评分或单个 supported 自动确认。

#### Scenario: Supported symptom is not a confirmed cause
- **WHEN** 证据仅支持连接池耗尽但不能解释为何耗尽
- **THEN** 系统 MUST 保持具体根因未确认，root_cause 为 null，并说明必要机制缺口。

#### Scenario: Existing explanation is refined
- **WHEN** 细化同一原因解释
- **THEN** 系统 MUST 保留 ID、重置该解释判断为 pending、失效当前旧关系与事故结论，并用已有证据重新评估；更换原因必须新增 ID。

#### Scenario: Investigation ends with unresolved hypotheses
- **WHEN** 整体调查结束
- **THEN** pending、investigating、blocked MUST 转 unresolved 并保留理由和缺口，supported/contradicted 不因结束而改变。

#### Scenario: New evidence warrants reopening
- **WHEN** 调查进行中新证据或阻碍解除改变旧判断
- **THEN** 系统 MUST 允许有依据地重新评估，并说明原因；整体终态后不得改写该次调查。

### Requirement: Bounded diagnostic investigation
诊断 SHALL 执行独立且不可兑换的预算：初始 5 轮、20 次工具、480 秒、两次内部往返，每批/并发最多 4。时间从首次实际开始计，不含排队；恢复 MUST 保留原截止和占用。未知发起状态 MUST 保守保留预算。

#### Scenario: Parallel calls consume correct budgets
- **WHEN** 一批三个独立调用实际发起
- **THEN** 系统 MUST 消耗一轮及三次调用，失败不返还；未发起计划不算实际调用。

#### Scenario: Fifth batch still requires analysis
- **WHEN** 第五轮或第 20 次调用已执行但结果尚待分析
- **THEN** 在时间允许时系统 MUST 分析结果及有限调整，禁止额外批次/调用，而非立刻丢弃结果。

#### Scenario: Shared internal budget is exhausted
- **WHEN** 两次不经工具的假设调整或空计划回流已用完
- **THEN** 系统 MUST 完成允许的最后评估，仍可构建有效查询；无法合法继续时才以 budget_exhausted 收尾，不允许第三次回流。

#### Scenario: Phase deadlines limit new work
- **WHEN** 达到 390、450 或 480 秒边界
- **THEN** 系统 MUST 分别停止探索、停止模型评估、停止全部新外部调用；不为报告或恢复延长调查预算。

#### Scenario: Call timeout precedes phase deadline
- **WHEN** 核心模型在阶段仍有时间时发生自身超时或接口错误
- **THEN** 系统 MUST 记录执行失败，不虚构 budget_exhausted；阶段截止引发停止则说明真实时间限制。

### Requirement: Query plan completeness and limited correction
查询计划 SHALL 区分可执行调用和未满足需求；超额、非法字段或参数最多针对性修正一次，失败仍非法 MUST 异常收尾。工具/模型接口失败 MUST NOT 自动重试，双空计划不得视为正常完成。

#### Scenario: Partially available information is queried
- **WHEN** 部分需求可独立查询而其他需求无法覆盖
- **THEN** 系统 MUST 执行有价值调用并反馈其余需求，不制造替代事实或机械裁剪超额调用。

#### Scenario: Initial plan cannot run
- **WHEN** 首轮无可执行调用但有明确未满足需求
- **THEN** 系统 MUST 在内部额度内回流判断替代路径或停止事实，尚未采证时保持空假设。

#### Scenario: Invalid output has already been corrected
- **WHEN** 同次节点输出针对性修正后仍非法
- **THEN** 系统 MUST 保存安全错误并程序收尾，不能重新开始修正计数。

### Requirement: Minimal first collection fallback
首轮全部失败或全部空业务结果 SHALL 不生成假设，直接程序收尾；有数据但合法空初始假设增量 SHALL 按初始化未完成处理。本期 MUST NOT 增加专门首轮补采循环或强迫虚构假设。

#### Scenario: Initial queries return no usable records
- **WHEN** 首轮全失败或业务结果全空，且没有适用停止事实
- **THEN** 系统 MUST 以 failed 和 stop_reason=null 保存初始化未完成及兜底，保留实际空结果/失败记录。

#### Scenario: Partial collection succeeds
- **WHEN** 部分工具失败但其他工具返回业务数据
- **THEN** 系统 MUST 继续生成及评估，不仅因一次工具失败判整次失败。

#### Scenario: Valid empty initial hypothesis update
- **WHEN** 模型依据已返回数据合法表示无法形成有依据的初始假设
- **THEN** 系统 MUST 明确初始化未完成，不把它当格式错误要求模型编造。

#### Scenario: Genuine stopping fact exists
- **WHEN** 无假设且已确有关键数据不可用或预算结束
- **THEN** 系统 MUST 使用真实停止原因，正常未确认收尾，不凭全空结果推定永久能力缺失。
