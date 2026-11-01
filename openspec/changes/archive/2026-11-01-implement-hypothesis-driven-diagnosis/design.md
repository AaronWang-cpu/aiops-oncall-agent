# Design

## Context

本设计是待审核的工程选择，业务原则来自交接文档，不表示实现已完成。动机见 `proposal.md`。

| 已核对现状 | 工程影响 |
|---|---|
| `aiops/diagnostics.py` 使用串行 executor 和不调用 LLM 的 evidence_reasoning，`compile()` 未接持久 checkpointer | 替换图内职责，不能把旧 checkpoint JSON 当成可续跑图 |
| `memory/sqlite.py` 的诊断写入方法分别 commit | 增加 Repository 一致提交入口，不能连续调用旧方法冒充事务 |
| `jobs/runtime.py` 在 handler 结束后单独标 job 终态，heartbeat 失效只结束续租 | 诊断必须自行一致收尾；Runtime 不覆盖已提交终态，失租后拒绝写入并停止调用 |
| `extended_sqlite.py` 领取递增 attempt，事件分配 sequence，已有 lease_owner/lease_expires_at | 复用这些字段作执行者校验、序号分配及恢复，不另建任务平台 |
| 证据存储包含 source/summary/payload，而公共枚举缺 change | 保留旧存储元数据，新增业务投影而非删列，修正共享类型 |
| 前端只过滤 planner/executor/replanner；旧主规格要求 SOP-first 和自动入库 | 更新新任务展示和 delta；保留历史展示及独立手动保存功能 |

## Goals / Non-Goals

**Goals:**

- 将已确认闭环拆成可以独立验证、依次合入的工程阶段。
- 在现有 SQLite/Repository 上保证调用记录、有效判断、恢复及终态的一致性。
- 保留现有受保护 HTTP 路径、统一 envelope、中文界面和用户作用域。

**Non-Goals:**

- 不引入新服务、另一个后端、RAG、评测平台、trace 平台或假设版本系统。
- 不改变聊天编排、检索排序、通用 MCP 重试默认值或其他后台 handler 的业务规则。
- 不压缩原始 Mock 日志、不创建预置答案模板、不改旧评测集、不执行新评测。
- 不实现真实指标/变更提供者；缺失能力明确反馈，不伪造。测试替身不等于生产接入。

## Decisions

### 1. 模块边界

保留 `AiopsDiagnosticService` 为现有注入入口，在 `apps/backend/src/super_ai/aiops/` 内增加以下聚焦模块，名称属于工程建议：

| 模块 | 职责 |
|---|---|
| `diagnosis_models.py` | Pydantic v2 严格业务模型、节点输出和引用校验 |
| `diagnosis_context.py` | JSON 配置、知识与场景快照；已有目录装配 |
| `diagnosis_budget.py` | 可注入时钟、阶段判断、轮次/调用/内部额度 |
| `diagnosis_tools.py` | 真实与 Mock 工具适配、参数约束、重复调用检查 |
| `diagnosis_reporting.py` | 权威头部、模型正文、程序兜底与历史判断标识 |
| `diagnostics.py` | LangGraph 节点、条件边和 Repository 调用 |

Repository Protocol 放在现有 `memory/repositories.py`；事务实现放在 `memory/sqlite.py` 或同目录聚焦实现，复用 session factory。网络连接仍由 lifespan/惰性注入创建。替代方案“把全部实现继续放进单文件”和“新建独立诊断服务”分别增加耦合或扩大范围，不采用。

### 2. 业务模型及模型输出

业务结构严格拒绝额外字段，JSON 对象使用现有 JsonDict 或明确 JSON 值类型，不用 `Any` 逃避校验：

| 业务对象 | 字段 |
|---|---|
| Hypothesis | `hypothesis_id / statement / hypothesis_status / assessment / evidence_links / gaps` |
| Evidence | `evidence_id / query_id / kind / data` |
| QueryRecord | `query_id / hypothesis_ids / question / tool_name / arguments / status / status_reason` |
| HypothesisRelation | `from_hypothesis_id / to_hypothesis_id / relation_type / explanation / evidence_ids` |
| IncidentConclusion | `conclusion_status / root_cause / stop_reason / explanation` |

假设状态为 `pending / investigating / supported / contradicted / blocked / unresolved`；证据关联为 `supports / contradicts / context`；关系为 `causal_link / competing`；现场证据为 `log / metric / change`。事故停止原因仅 `root_cause_confirmed / budget_exhausted / critical_data_unavailable` 或 null。

节点输出契约：

- `revise_hypotheses`：仅 `new_hypotheses` 和 `revised_hypotheses`；新增项仅 statement，修改项仅 hypothesis_id/statement。程序分配 ID、增量应用、重置修改项判断字段，失效当前关系与结论；未修改项保持。
- `assess_hypotheses`：`hypothesis_assessments / hypothesis_relations / incident_conclusion / next_step`。第一项是全部当前 ID 的五字段判断更新：`hypothesis_id / hypothesis_status / assessment / evidence_links / gaps`，不输出 statement。后两项为四字段事故结论和 `action / reason / requests`，请求为 `hypothesis_ids / requirement`。
- `build_queries`：直接输出 `calls / unmet_requests`，程序装入图状态 `query_plan`。调用为四字段，未满足项为三字段，严格沿用交接文档。
- `report`：模型仅返回中文 Markdown 正文；程序组装四部分报告及权威头部，持久化纯 Markdown，HTTP/SSE 不改为 JSON 报告。

完整集合校验包括 ID 恰好一次、合法引用、无自关系和反向重复竞争关系；`confirmed` 要求非空 root_cause 且停止原因 `root_cause_confirmed`，`unconfirmed` 的 root_cause 必须 null。调查继续时停止原因应为空；合法 finalize 需真实适用停止条件，纯执行失败由程序异常路径收尾。最终分析模式只允许 `next_step.action = finalize`、requests 为空。

模型语义标准写入 prompt：原因具体、对应对象/时间/机制有证据、无关键反证或主要未决竞争解释。引用合法不证明因果正确。一次结构错误只发一次携带原输出和安全校验错误的修正请求；接口错误不修正、不重试。初次合法空假设增量属于初始化未完成，而非 JSON 错误。

### 3. 状态存储与公共投影

选择 Repository 管理的完整状态 checkpoint，而非本期新增 LangGraph SQLite saver 依赖：LangGraph 负责图路由，Repository 是持久事实来源。每个节点提交后才推进下一节点；恢复通过 START 的程序条件边进入已保存 next_node，不重跑 prepare_context。不是“原样 compile 即可续跑”。

现有 `aiops_graph_checkpoints.checkpoint_payload` 保存内部 `runtime / working_state / last_valid_assessment`，历史 checkpoint 保留。大体积原始结果只存 evidence，checkpoint 引用 ID；恢复后由 owner-scoped Repository 解引用为完整模型输入，不以摘要代替。

| 内部部分 | 内容与作用 |
|---|---|
| runtime | 引擎标识 `hypothesis-driven-v1`、next_node、已提交节点序号、阶段、固定时间、计数、模型请求 intent、修正占用、批次及调用 intent |
| working_state | 当前假设、关系/结论有效性、next_step、query_plan、执行记录关联、未满足需求及未分析证据 ID |
| last_valid_assessment | 一致假设/关系/结论快照、已分析证据 ID、对应步骤序号 |

`prepare_context` 一致保存模式、场景及知识/目录快照。内部引擎标识用于历史兼容，不是新增假设版本字段。`result_payload` 保留已有外壳，新增键 `diagnosis` 为类型化公共投影：`engine / mode / hypotheses / hypothesis_relations / incident_conclusion / query_records / tool_evidence / unmet_requests / unassessed_evidence_ids / assessment_is_current / budget`。预算区分实际次数和未确定占用，不能把预占当实际调用。

该外层对象只汇总既有业务结构及执行元数据，不重复维护第二份根因结论。旧 resultPayload 没有 diagnosis 时按历史解析。API 仍返回原 `inputPayload / resultPayload / evidence / reports / checkpoints` 外壳；共享类型增加可选 diagnosis 和 type guard，新增模型内键按原业务 snake_case，不强行重命名历史 DTO。

Evidence 投影：storage.id → evidence_id，tool_call_id → query_id，kind → kind，payload → data；source/summary 等旧字段继续保存但不作为业务字段。QueryRecord 从完成的审计与节点调用上下文组装，audit.id 作为 query_id，审计 `completed` 映射 succeeded、`failed` 映射 failed。兼容读取旧 aiops_tool_call_audits；新写入继续沿用当前 tool_call_audits，不能双写出两个实际调用。

内部 checkpoint 的调用 intent、原模型错误输出、凭据和知识内容不原样推送；证据链返回安全公开投影，模型仍在后端读取完整脱敏结果。历史授权与脱敏不放宽。

### 4. 四类一致提交操作

在同一 SQLite transaction 内校验 owner、task/job 关联、当前 lease_owner、未过期租约及本次 claim 的 attempt；多 worker 领取使用条件更新或序列化写入，旧执行者不能通过同名 worker 或过期租约写入。现有 attempt 作为领取代次，不新增租约版本列。

| Repository 操作建议 | 同事务提交内容 |
|---|---|
| `reserve_diagnostic_operation` | 模型/工具 intent、预算占用及调用或批次身份，校验下一操作权限 |
| `commit_diagnostic_query` | 终态审计、七字段查询上下文、完整/部分 evidence、工作状态和工具完成事件 |
| `commit_diagnostic_node` | 有序步骤、有效节点更新、必要有效评估快照、next_node 和进度事件 |
| `finish_diagnostic_job` | 程序报告、证据链接、最终调查状态、诊断与 job 终态、report/error/task.status/complete |

网络请求不放进 SQLite transaction。并行工具只并行外部请求，返回后通过事务协调器更新最新持久状态，不能各自覆盖一份过期 JSON。事件 sequence 在同事务分配，唯一约束冲突回滚本次落盘而非重发外部调用。

同一节点/调用/终止身份使用稳定主键及已提交状态作幂等检查；报告、步骤及 checkpoint 使用程序生成稳定 ID。复用现有 primary key，不依赖“先查再插”的无锁幂等；重复提交的合法同内容可读取既有结果，不一致内容拒绝。

优先不改 schema。若现有字段无法满足约束，应在开始对应任务前提出具体迁移与测试；不凭猜测新增表，也不修改已发布 revision。

### 5. 图路由及预算

正常入口：prepare_context → build_queries → execute_queries → revise_hypotheses → assess_hypotheses。后续条件边仅映射已校验 next_step；finalize 是独立程序节点，随后 report → END。

首轮无业务数据直接程序兜底；首轮有业务数据但无法形成假设按初始化失败处理。无调用但有 unmet_requests 使用有限回流，尚未采证时评估不得生成初始假设；双空计划属于非法输出。节点异常捕获进入程序 finalize/report，不添加模型路由节点。

| 参数建议 | 初始值 | 校验 |
|---|---:|---|
| maxRounds / maxToolCalls | 5 / 20 | 正整数，不互相兑换 |
| maxCallsPerBatch / maxConcurrentCalls | 4 / 4 | 正整数，实际并发取批次、预算及工具限制最小值 |
| maxInternalSteps | 2 | 两种内部往返共享，不是所有模型调用总数 |
| investigationSeconds / finalAnalysisSeconds / reportSeconds | 390 / 60 / 30 | 均为正，总和等于 totalSeconds |
| totalSeconds / toolTimeoutSeconds / modelTimeoutSeconds | 480 / 60 / 60 | 阶段剩余时间和连接/模型配置共同限制 |

时钟可注入。持久化 UTC started_at 和三个绝对 deadline，运行中用 monotonic 防止节点重复起算，恢复按原 UTC deadline 计算剩余时间；机器时钟变化属于运行限制，必须告警，不通过恢复重置时间。

预占预算后发起外部请求，实际发起更新实际计数；崩溃不能确定是否发起时保留占用但另标 unknown。同批首个调用只计一轮；后续同批调用仍可在第 5 轮发起。调用前与条件边均检查，批次不随分波改 ID。明确未发起可释放占用；没有实际调用且无 unknown 的计划不计轮。

内部回流在返回评估前计一次，实际批次结束后才重置；第 2 次往返后的评估仍允许完成，之后仍允许有价值的实际查询。次数/轮数耗尽不跳过最后一批分析；390 秒后不启动工具、构建或细化，必要时仅最后评估，450 秒后仅报告，480 秒后仅程序持久化及交付。提前结束不等待阶段边界。

单次失败不取消其他独立调用，不在批内逐工具模型重规划。发起后的取消/超时记录失败，未发起计划不写查询记录；请求取消不保证远端终止。截止时已收到数据先保存，最终分析冻结证据集合；冻结后但终态提交前保存的数据显式未分析，不静默加入结论。终态提交后不接收结果来改写已完成调查，未能保留的迟到结果记录局限，不无限等待。

### 6. 诊断专用客户端与内容文件

LLM 使用现有 Qwen/Bailian 配置创建独立 `max_retries = 0` 实例，MCP 使用诊断策略覆盖 retries=0，包括发现；不改用户连接记录或全局实例。工具定义按用户作用域发现后一次固定，无可用工具明确能力缺口。真实查询仍使用实际定义、超时、脱敏、同名工具保护及审计。

工具参数差异保留：SearchLog 从告警服务和窗口启动，后续有依据可扩其他服务；QueryMetric 按目录校验模型选择；QueryChange 程序构造告警服务和一级依赖，后续依据推理扩查。真实模式只暴露已接入能力，不把本地 Mock metric/change 注册成真实工具。相同失败参数不可换 ID 重试，有新数据条件的必要补查须说明价值并占预算。

配置仅从现有 merged JSON 读取 `aiopsDiagnosis`：

```json
{
  "mode": "real",
  "mockScenarioPath": "",
  "projectKnowledgePath": "",
  "maxRounds": 5,
  "maxToolCalls": 20,
  "maxCallsPerBatch": 4,
  "maxConcurrentCalls": 4,
  "maxInternalSteps": 2,
  "investigationSeconds": 390,
  "finalAnalysisSeconds": 60,
  "reportSeconds": 30,
  "totalSeconds": 480,
  "toolTimeoutSeconds": 60,
  "modelTimeoutSeconds": 60
}
```

旧配置缺分组时采用上述安全默认；分组存在但类型/值非法则报配置错误，布尔值不能当整数。模板 default real，用户模板仅必要覆盖；不给前端配置编辑器新增范围。

相对内容路径相对 Git 仓库根目录解析，绝对路径只接受操作者 JSON 配置，不接受前端任意路径。建议本地知识 `config/aiops-project-knowledge.yaml` 并忽略，空模板 `config/aiops-project-knowledge.template.yaml`；开发场景放 `apps/backend/src/super_ai/aiops/mock_scenarios/*.json`，不属于评测资产。

知识 YAML 使用 safe_load：project_overview 为字符串，services 为服务名到 description 的映射，未知内容为空；无路径允许空知识，显式配置缺失/非法则 prepare_context 失败并兜底。任务开始读取后固定，不打印知识全文，不按知识编造现场 evidence。

场景文件只含告警、日志、指标时间序列和变更；按服务/实例、统一相对时间基准固定一次快照，各工具按参数过滤。场景中不含 expected_root_cause、评分或模板答案；未支持查询语法/参数明确失败或缺口，不能忽略过滤条件返回全部数据。Mock 模式标识在 task/result/report；真实模式不失败回退。先提供一个正常闭环场景及一个干扰/缺失场景用于单元和组件验收，不新增评测。

### 7. 恢复、取消与 Runtime 集成

每次 claim 将 worker_id 和 attempt 注入 context，写入前及调用前校验有效租约。heartbeat 失效应请求本地取消并停写，外部旧请求可能已执行但不能继续推进任务。诊断 max_attempts=1；租约过期再次领取是同任务恢复，不是普通失败重试。

| 恢复内容 | 执行方式 |
|---|---|
| 已提交 next_node | START 条件边进入该节点，重建完整结果，不重跑已提交节点 |
| 已完成查询 | 复用 evidence/审计，不再发起 |
| 工具 intent 未获得可确认结果 | 保留占用和 unknown，恢复为带中断原因的 failed；不作为反证、不重放；有替代路径及预算时继续 |
| 模型 intent 未有完整有效提交 | 核心阶段按执行异常程序收尾；报告阶段直接程序兜底 |
| 终态已一致提交 | 仅重放持久事件，不再调用 handler 或改写终态 |
| 恢复超过 deadline | 仅运行当前阶段允许操作，总截止后只程序兜底和持久化 |

取消请求与 finish 使用相同 job 写入协调，取消先提交则最终 cancelled，终态先提交则保留既有终态并明确不能再取消。queued 取消尚未 prepare 时不加载外部资源，只保存程序说明。Runtime 的 handler 结束路径识别诊断已提交 job 终态，不再 mark_succeeded、handle_failure 或二次取消覆盖。未成功落盘不能让 Runtime 单独报告成功。

外层诊断 watchdog 建议为 totalSeconds 加 30 秒程序落盘保护；额外时间绝不用于模型/工具，不声明硬预算内必然完成磁盘写入。数据库不可用时不保证即时报告；保留可恢复意图，在可用后由恢复收尾，不另起无限重试循环。

现有显式后台 retry 使用相同 resource_id，与“已终态调查不可修改”不兼容。工程建议：诊断的显式重试创建新的 diagnostic task 和新 job，保留原 task/report；其他 job 重试保持原行为。这只由用户主动操作触发，不改变自动重试规则，不增加查询 retry_of。

### 8. 报告和 SSE

report 先生成待提交 Markdown：程序结论头部 + 模型正文四部分。正文无效、空或与已有结论存在可检测冲突时直接程序兜底，不再请求修正。报告不补充事故根因，不执行处置；建议标明前提和风险。

输入首选本次有效最终评估；否则历史有效快照只能标“此前判断”，未评估新证据和新解释单列局限；当前终态 unresolved 不由历史 supported 覆盖。曾确认的判断遇到尚未评估、可能改变结论的新内容，不把历史 confirmed 冒充当前确认，当前头部明确未完成最新验证。仅报告生成失败不降级已有效的当前结论。

finish transaction 按既定表同时保存 diagnostic/job：

- 有效确认、正常预算结束或真正关键数据不可用：succeeded。
- 核心执行失败或初始化未完成：failed，无适用 stop_reason 时 null。
- 用户取消：cancelled，不请求报告模型。
- 报告单独失败但兜底成功：沿用原终态，不升级或降级结论。

有报告时 report → 失败时 error → task.status → complete。`error` 复用统一错误结构；仅 aiops 流必须继续消费到 complete，聊天 parser 不改变。工具失败仍为 tool.call failed。

不新增 SSE 类型；aiops task.status 增加可选安全 phase 及类型化 diagnosis 进度，complete.result 为已有最终任务投影。落盘事件 ID 作为 SSE id 行和 JSON id，sequence 唯一；POST stream 支持 `Last-Event-ID` 恢复，首开无 cursor 从头读，cursor 必须属于该用户及 job。前端保留最后事件 ID、去重并在 EOF 后回载终态；缺 complete 是不完整流而非成功。订阅层不临时合成与持久状态不一致的终止事件。

### 9. 前端与历史兼容

共享包先增加业务类型、AiopsEvidenceKind.change、diagnosis 可选投影及新 SSE 字段，再同步后端/parser/store。新节点中文标题覆盖七节点；历史 planner/executor/replanner/evidence_reasoning/report 有兼容标题，未知节点显示原名，不过滤。

沿用现有中间 Markdown 报告和右栏可折叠工具展示，增加假设状态、依据/缺口及事故确认/停止状态；完整原始数据保留在 API，界面摘要不回流成为模型唯一证据。任务 failed 即使有报告也显示失败；Mock task/report 可见“模拟场景”，历史未知模式不擅自标真实。保留反馈、独立手动保存、桌面内部滚动及窄屏纵向重排。

### 10. Git 分支和提交建议

以下仅供审核，当前未执行任何 Git 写操作：

- 候选基线：`feature/multi-source-evidence-architecture` 的 `b94f8bd`；实施前重新检查 HEAD、上游及用户改动。
- 建议新分支：`feature/hypothesis-driven-diagnosis`，直接基于该基线保留已完成三阶段提交，不切到未知 main，不 rebase/amend 旧历史。
- 授权建分支后先提交交接文档、本 change 和生成 WIKI，建议 `docs: specify hypothesis-driven diagnosis workflow`。
- 随后每阶段连同目标测试一起提交；未通过本阶段验证不提交，不把实际功能拆成无测试的孤立提交：

| 阶段 | 建议新提交 | 范围 |
|---|---|---|
| P1 | `feat: define hypothesis-driven diagnosis contracts` | 共享/后端模型、配置及合法性测试 |
| P2 | `feat: persist resumable diagnosis operations` | 一致事务、租约/预算保护、恢复和 Runtime 接口及故障测试 |
| P3 | `feat: add isolated diagnosis context and tools` | 固定知识/场景、真实入口、无重试与参数校验 |
| P4 | `feat: implement hypothesis-driven diagnosis graph` | 七节点、并发、内部循环、时间控制、报告/SSE 后端闭环 |
| P5 | `feat: display diagnosis hypotheses and outcomes` | 前端/parser/store、新旧兼容及响应式测试 |
| P6 | `docs: align diagnosis specifications and operations` | 全量验证、操作说明、主规格同步及归档/WIKI |

P1-P3 不切换现有默认执行入口；P4 后先后端验收，再 P5 开放前端新展示；不要宣称未完整阶段已可生产使用。实际差异过大可在不拆散验收边界的前提下增加小提交，仍需授权。

逐文件 staging，不包含 config/project.json、user.project.json、数据库、缓存、截图临时件或 eval_results。每次新 commit，禁止 amend/force push；不自动 merge、push、PR 或归档。授权规格不等于授权全部提交；确认分支/首次提交后，后续仍按用户指定授权范围执行。

## Risks / Trade-offs

- [网络瞬时失败直接收尾] → 明确执行错误及有效快照，遵守无自动重试，不用兜底掩盖失败。
- [调用前预占与实际发起不可原子化] → 崩溃时保留未知占用、不重放，接受可能少用额度，不声称 exactly-once 外部执行。
- [完整证据可能超过上下文] → 不静默截断或摘要替代，明确失败和未分析范围；压缩需另行批准。
- [模型结构合法仍可能错误] → 证据/知识隔离、确认标准、反证及竞争解释测试，不用评分冒充可信度。
- [共享 Runtime 修改影响其他任务] → 诊断特化事务及终态识别，回归索引、聊天和 MCP 管理。
- [磁盘或进程故障无法即时交付] → 成功提交后才发终态，恢复幂等补交付，不保证不可用期间完成。
- [租约防护需要改变 Repository 写路径] → 先 P2 故障注入验证再接真实客户端，不能只加 heartbeat。

## Migration Plan

1. 用户审核工程规格和 Git 安排，再授权分支及实施范围。本轮主规格不改。
2. 增加可选契约和默认配置，旧 resultPayload/步骤读路径保持；不强迁历史 JSON。
3. 事务/租约及客户端验证后接入新图；开始时固定 engine/mode，恢复不按新配置改模式。
4. 升级前端及诊断 SSE parser，联合验收。运行中旧引擎任务升级前排空；旧 checkpoint 不强转新引擎，必要时按真实中断程序收尾。
5. 回退使用新的 revert commit 并按依赖阶段协调前后端，不 reset 历史或删除任务数据；新引擎运行中任务先安全停止，不交给旧 runner 从头执行。
6. 所有 tasks 完成及用户确认后再同步主规格、归档并发布 WIKI；不能凭规格构建通过标实施完成。

## Open Questions

不保留会改变主方案的未决架构选择。待实现时可确定的内容仅为实际项目知识文字、场景具体业务字段及目标工具返回细节；由提供者验证，不读取评测答案推导。若现有 SQLite 字段或真实工具不支持设计边界，先提出明确影响供用户确认，再调整规格或新增迁移。
