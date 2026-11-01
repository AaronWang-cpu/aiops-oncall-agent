# 假设驱动诊断运行说明

关联变更：[implement-hypothesis-driven-diagnosis](/changes/archive/2026-11-01-implement-hypothesis-driven-diagnosis/)（已归档）。

## 实施状态

本页随实现更新，不把已确认设计当作已完成能力：

| 阶段 | 状态 |
|---|---|
| P1 业务模型、共享契约和配置 | 阶段验收通过；未切换诊断入口 |
| P2 一致持久化与恢复 | 持久底座和恢复策略验收通过；新图接线仍在 P4 |
| P3 固定上下文与隔离工具 | 上下文与工具适配器验收通过；七节点调用在 P4 接线 |
| P4 假设图、预算与报告 | 后端七节点、报告、终态与 SSE 验收通过；旧图已替换 |
| P5 前端展示与兼容 | 三栏工作区、假设与事故结论展示、模拟/失败标识、流去重与续读验收通过；浏览器截图在 P6 获取授权后提供 |
| P6 联合验收与本机启动 | 后端/前端/契约全量回归与跨 owner 隔离、脱敏集成测试完成；本机启动与浏览器体检、主规格归档待用户授权 |

## 诊断配置

应用配置仍只从 `config/project.json` 与 `config/user.project.json` 递归合并加载。在 `aiopsDiagnosis` 分组中设置下列字段，未提供该分组的旧配置采用安全默认：

| 字段 | 默认 | 含义 |
|---|---|---|
| mode | real | 默认真实模式；只有明确选择 mock 才允许模拟 |
| mockScenarioPath | 空字符串 | mock 模式必须填写场景内容文件路径 |
| projectKnowledgePath | 空字符串 | 可选项目知识 YAML 路径 |
| maxRounds | 5 | 实际查询批次额度 |
| maxToolCalls | 20 | 实际工具调用额度 |
| maxCallsPerBatch | 4 | 单批计划上限 |
| maxConcurrentCalls | 4 | 外部工具最大并发 |
| maxInternalSteps | 2 | 不经工具的两类内部往返共享上限 |
| investigationSeconds | 390 | 探索时间 |
| finalAnalysisSeconds | 60 | 最后分析保留时间 |
| reportSeconds | 30 | 报告保留时间 |
| totalSeconds | 480 | 三个阶段的总时长 |
| toolTimeoutSeconds | 60 | 单次工具请求上限 |
| modelTimeoutSeconds | 60 | 单次模型请求上限 |

数值必须是正整数，阶段之和必须等于总时长；非法值、布尔值及未知字段直接拒绝，不自动裁剪或扩展预算。配置加载不会建立网络连接，P1 的 Mock 配置校验不表示工具及场景已接入。

模板只保存空密钥与安全默认；本地配置、私有知识和真实日志不得提交。内容路径和知识加载在 P3 接入，前端不能提交任意本地文件路径。

## 内容快照与模式隔离

诊断开始时读取一次内容，之后由 checkpoint 决定恢复，不再回读文件：

- 项目知识从 `projectKnowledgePath` 读取。相对路径按仓库根解析，也接受绝对路径；文件缺失或结构非法直接失败，不静默退化为空知识。
- 知识只作为背景信息参与推理，不分配现场 `evidence_id`，也不进入证据链。
- `config/aiops-project-knowledge.template.yaml` 是空模板，不是应用配置；填写后的本地文件已被忽略规则排除。
- Mock 场景是显式 JSON 事实快照，只包含告警、日志、指标和变更，不含期望根因、评分或任何评测答案，也不引用旧的评测资产。

两种模式互不替代：

- 默认 real：只暴露当前登录用户已启用连接中实际发现的工具。缺少某项能力时如实返回未满足需求，真实失败不模拟回退。
- 显式 mock：只按请求参数在固定快照内筛选，参数不含时间范围之外的隐藏条件；改变时间窗口不会移动已记录事实，重复同一查询返回相同事实。

诊断专用调用与聊天/连接管理隔离：模型实例强制 `maxRetries=0` 并把超时收敛到配置上限，存储连接的 `retries` 不被改写；MCP 调用使用已发现的固定工具身份，不在调用时重新发现，也不自动重试。

要在本地演示模拟流程，把 `aiopsDiagnosis` 指向随仓库提供的场景文件即可（路径相对仓库根）：

```json
{
  "aiopsDiagnosis": {
    "mode": "mock",
    "mockScenarioPath": "apps/backend/src/super_ai/aiops/mock_scenarios/order-pool-exhaustion.json",
    "projectKnowledgePath": "config/aiops-project-knowledge.yaml"
  }
}
```

`projectKnowledgePath` 指向的文件需自行创建；缺失或非法时诊断会明确失败，不会改用空知识继续。

## 业务契约

- 假设：六字段，解释由调整节点写入，判断由评估节点写入。
- 证据：四字段，只表示实际工具完整脱敏结果；支持 log、metric、change。
- 查询：七字段，只在调用结束后表示 succeeded/failed，不用它记录计划中或执行中状态。
- 关系：五字段，causal_link 有方向，competing 仅保存一条；关键引用限于本次调查。
- 事故结论：四字段；unconfirmed 的 root_cause 必须为空，confirmed 需要具体原因与 root_cause_confirmed。

共享包的 `isDiagnosisResult` 使用与 OpenAPI 相同的 schema 校验 API 投影；后端另行校验当前假设完整集合、工具能力与同次证据引用。结构合法不等于因果已证实，后续评估仍须核实对象、时间、机制和竞争解释。

现有 HTTP 路径与 envelope 保留，旧 resultPayload 无 diagnosis 时仍可读取。诊断进度的新阶段字段可选，聊天 SSE 字段和行为不因 P1 改变。

## 阶段验证

后端在 `apps/backend` 执行：

```powershell
uv run pytest tests/test_diagnosis_models.py tests/test_diagnosis_config.py
uv run ruff check .
uv run pyright
```

共享包与前端在仓库根执行：

```powershell
npm run contracts:typecheck
npm --workspace packages/api-contracts run test
npm run frontend:typecheck
npm run frontend:test -- --run tests/aiopsStore.test.ts
npm run docs:build
```

此处命令是阶段验证方式，不表示已完成全量实施或已执行真实模型/CLS 请求。

P3 目标测试为：

```powershell
uv run pytest tests/test_diagnosis_context.py tests/test_diagnosis_tools.py tests/test_evidence_tools.py tests/test_mcp_observability.py tests/test_llm_provider.py
```

### P1 实际结果

- 目标后端测试：44 项通过；新增代码与测试的 Ruff、strict Pyright 均通过。
- 共享包：34 项测试及类型检查通过。
- 前端：类型检查及 3 项 AIOps store 回归通过。API 快照使用 shallowRef，保留整体替换更新方式，避免递归 JSON 类型触发 Vue 深层类型展开。
- 文档构建通过。全后端静态检查仍有此前代码的 212 项 Ruff 问题及 9 项 Pyright 问题，不涉及新增 P1 模块；后续阶段需要按模块收口，未关闭检查或修改旧评测数据。

### P2 实际结果

- 100 项测试通过，包含预算、恢复策略、事务、Runtime、迁移、旧诊断和认证回归。本阶段改动及新增测试的 Ruff、strict Pyright 通过；尚未再次完成全后端静态检查。
- 复用现有表，未修改 schema 或已有迁移。四类 Repository 操作在短 SQLite 写事务内校验 owner、task/job 关联、租约有效期及 attempt；网络请求不在事务中。
- 故障注入覆盖预占、步骤、证据、审计、报告、链接、事件和 checkpoint，验证失败整体回滚；相同稳定身份重入不重复写入，不同内容不能复用身份。
- 后台领取、续租、事件及终态写入校验代次。失租停止本地 handler；已发出的远端请求不能保证撤销，也不声称外部请求具备 exactly-once 语义。
- 排队诊断取消一致保存程序报告和结束事件，不加载外部资源。运行中取消停止新调用，完成提交与取消请求以先提交决定为准，已有部分结果保留。
- 显式诊断重试创建新 task/job，旧状态和报告不改写；普通 job 保留原重试资源与退避策略。取消终态任务返回冲突，非 owner 返回授权错误。
- 修正旧依赖装配：已注入的诊断 runner 不再额外初始化 Milvus，保留原权限和流断言。

### P3 实际结果

- 新增 `diagnosis_context.py`、`diagnosis_tools.py` 及 63 项目标测试；本阶段改动与新增测试的 Ruff、strict Pyright 通过。
- 内容只在准备阶段读取一次：`restore_diagnosis_context` 不接受配置或路径，删除原文件后仍能从快照恢复；知识与目录不进入证据链。
- 空知识模板与本地私有内容已被忽略规则隔离；场景文件为固定事实，测试断言其中不出现期望根因、评分或旧评测资产字段。
- Mock 筛选按服务/实例/级别/时间窗/指标白名单/维度/变更类型严格匹配，未知参数与非法时间范围直接拒绝而不是忽略；重复同一查询返回相同事实。
- 真实入口只使用当前 owner 已发现的工具身份，单次调用、无自动重试、无 Mock 回退；能力缺失返回未满足需求。
- 未执行真实模型或 CLS 请求，也未运行或修改评测数据；旧诊断默认入口仍为旧图，七节点调用在 P4 接线。

## 七节点执行与预算

诊断由持久后台任务执行，LangGraph 只负责路由，持久事实仍由 Repository 事务提交：

```text
START（恢复条件边）→ prepare_context → build_queries → execute_queries
→ revise_hypotheses → assess_hypotheses → 条件分支 build_queries / revise_hypotheses / finalize
→ report → END
```

- `prepare_context` 固定模式、知识与目录快照及可用工具，不重新读取文件。
- `build_queries` 输出可执行调用与未满足需求；双空计划非法，超额不静默裁剪；参数按模式补齐（日志从告警服务与窗口启动，指标按目录白名单，变更使用告警服务与一级依赖），未知参数按非法输出处理。
- `execute_queries` 先在同一事务保存调用 intent 与实际发起计数，再并发请求（并发取批次、预算与剩余额度最小值；剩余时间不足时退化为串行），返回后逐个提交终态审计、完整证据与查询记录。单次失败不影响其他调用，也不写未发起的查询记录。
- `revise_hypotheses` 只返回增量：新增项由程序分配 ID，细化项保留 ID 并重置为待评估，同时失效当前关系与结论。
- `assess_hypotheses` 覆盖全部当前假设，完整替换关系并给出事故结论与下一动作；最后分析阶段只能收尾。
- `finalize` 把未决假设转为 unresolved 并确定终态：确认根因为 succeeded，正常预算结束为 succeeded，关键数据不可用为 succeeded，初始化未完成或核心执行失败为 failed，停止原因只在真实适用时填写。
- 首轮全部失败或全部空业务结果不生成假设，直接程序收尾；有数据但空假设增量按初始化未完成处理。

预算继续使用 5 轮 / 20 次调用 / 两次内部往返 / 4 并发与 390/450/480 秒边界：额度耗尽不会跳过最后一批分析，内部额度耗尽不禁有效的新查询，截止时间按 UTC 绝对期限执行且恢复不重置。

## 报告与 SSE

报告由程序头部与四部分正文组成：`## 诊断结论`、`## 原因与证据`、`## 调查结果与局限`、`## 后续建议`。头部固定结论状态、停止原因、判断时效、执行模式与生成时间；正文优先使用模型输出，无效、为空或与已确认结论冲突时改用程序兜底，报告不首次补出未验证的因果链，也不执行处置。Mock 报告显式标注“模拟场景”。

终态在同一事务内保存任务、job、报告、证据链接与终止事件，顺序为：

```text
report → （仅整次失败时 error）→ task.status → complete
```

SSE 使用持久事件 ID 作为 `id:` 行与 JSON `id`，sequence 唯一；`POST /aiops/diagnostics/{id}:stream` 支持 `Last-Event-ID` 续读，缺省从头读取，游标必须属于该用户与该 job；缺 `complete` 视为不完整流，订阅层不再临时合成终止事件。聊天 SSE 行为不变。

## 持久恢复边界

checkpoint 保存 runtime、working_state 和 last_valid_assessment；原始工具结果仅存证据，通过当前用户、当前任务的引用回载完整数据，不用摘要恢复推理。

调用前先持久保存 intent 和预算预占。只有明确知道已发起时才保存实际调用计数；恢复时，未确定发起的预占转为 unknown 保守占用，已明确发起但未提交结果的调用保留实际计数及轮次，不退还额度。恢复不重发原调用，中断查询保存失败说明，不作为假设反证。

`plan_diagnostic_recovery` 仅分类已保存阶段和中断状态，不调用模型或工具。已提交节点从 next_node 继续；核心模型意图中断进入程序失败收尾，报告模型中断使用程序兜底。UTC 截止和已保存剩余时间不重置，停机等待扣除预算，390/450/480 秒之后仅允许对应阶段工作。

Runtime 支持诊断专用 on_termination 回调，统一处理取消、watchdog 超时及未提交终态的 handler 返回；不会覆盖已提交诊断终态。终态持久化不可用时保留可恢复 job，不单独宣布成功。`aiops_diagnosis` 已注册该回调，默认入口改为假设驱动诊断。

### P4 实际结果

- 新增 `diagnosis_reporting.py`，重写 `diagnostics.py` 为七节点图，`api/app.py` 改用持久终态回调与 `Last-Event-ID` 续读；新增 8 项图闭环测试并迁移旧诊断测试。
- 目标后端测试通过：`test_diagnosis_graph.py`、迁移后的 `test_aiops_diagnostics.py`，以及 P1-P3 诊断测试；本阶段改动与新增测试的 Ruff、strict Pyright 通过。
- 端到端（Mock 场景 + 脚本化模型 + 真实 SQLite 仓库）验证：三路采证、两个假设、确认根因、四部分报告、证据链接与 `report/task.status/complete` 顺序；首轮全空返回 failed 且 `stop_reason=null`；一次结构错误被针对性修正，重复非法输出程序失败；取消由 finalizer 一致提交。
- 未执行真实模型或 CLS 请求，未运行或修改评测数据。前端新旧兼容展示记录在下方 P5 章节。全后端仍有此前代码的既有 Ruff/Pyright 问题（集中在 `aiops/eval_*` 等旧模块），未在本阶段删除测试或放宽 strict。

## 前端展示与兼容

AIOps 工作区按左（输入、告警、历史）、中（任务卡片、实时过程、持久报告）、右（证据链、案例库）三栏组织，桌面固定高度、各自内部滚动，窄屏纵向重排且不产生页面横向溢出。

- 右栏执行链展示全部持久步骤：七节点中文标题、历史 `planner/executor/replanner/evidence_reasoning` 兼容标题，未知节点显示原始名称，不过滤。
- 假设区展示假设状态、依据（支持/反驳/背景）、关键缺口与假设关系；事故结论单独展示，`unconfirmed` 明确显示“具体根因尚未确认”，不把 `supported` 当作事故根因。
- 判断时效以 `assessment_is_current` 与未分析证据数提示，历史快照与当前内容不混用。
- 模拟模式显示“模拟场景”标识；历史结果缺失模式时不擅自标注真实。任务 `failed` 即使存在兜底报告也同时显示失败，不改为成功。
- 流消费按事件 ID 去重并保存游标，`error` 之后继续消费到 `complete`；无 `complete` 的 EOF 回载持久终态并按游标续读一次，不把不完整流当作成功，不重新创建诊断。客户端 `streamDiagnostic` 支持 `Last-Event-ID`，聊天 SSE 消费行为不变。

### P5 实际结果

- 新增 `diagnosis` 投影（`activeDiagnosis`）与流游标、去重、续读逻辑；`aiopsClient.streamDiagnostic` 支持 `Last-Event-ID`；`AiopsEvidenceChain`、`AiopsTimeline`、`AiopsReportPanel`、`AiopsView` 同步七节点与假设展示。
- 前端 `npm run frontend:typecheck`、`npm run frontend:test`（22 文件 / 93 项）、`npm run frontend:build` 全部通过；修复基线中两处既有前端失败（布局与案例库选择断言）。
- 未发起真实模型或 CLS 请求，未做浏览器桌面/窄屏验收；截图与本机启动属于 P6，需单独授权。

## 联合验收与隔离

`test_diagnosis_integration.py` 用真实 SQLite 仓库、真实 job runtime、HTTP/SSE 端点和传输替身贯通主路径：

- Mock 场景经 `POST /aiops/diagnostics` → `:stream` → 证据链回载：七节点步骤、3 条成功查询、确认结论、四部分报告与 `report/task.status/complete` 顺序；重复订阅只重放已持久事件，不重新运行诊断。
- 真实模式用 `LocalMcpClient` 传输替身：每次工具调用只发起一次（无自动重试），`mode` 为 `real`，报告不出现“模拟场景”；工具失败时查询记录为 `failed`，且不写入模拟证据、不伪造假设与根因。
- 取消：排队任务取消不调用模型、不加载外部资源、不产出调查投影。
- 跨 owner：他人任务流与证据链返回 403 且不回显任务 ID；`Last-Event-ID` 必须属于同一 user 与同一 job，否则 404。
- 脱敏：工具错误中的 `sk-*`、`AKID*` 凭据在查询记录、诊断投影与 job 事件中统一替换为 `[redacted]`。

### P6 实际结果

- 后端全量 `uv run pytest` 收集 361 项，10 项失败均为本地环境既有问题：Milvus 未启动 6 项（`test_chat_sessions_api.py`、`test_stream_rag_chat_api.py`）、`bash` 不可用 1 项（`test_local_development_docs.py`）、本地 `config/project.json` 与 `config/user.project.json` 不符合模板期望 3 项（`test_environment_examples.py`）。未 skip 测试或放宽断言。
- `uv run ruff check .` 报 212 项、`uv run pyright` 报 9 项，全部位于既有模块（`aiops/eval_fixtures.py` 197 项、`aiops/eval_runner.py`、`aiops/evidence_tools.py`、`aiops/catalogs/*`、`tests/test_eval_fixtures.py`、`tests/test_evidence_tools.py`）；本阶段新增与改动文件为 0 项。
- 前端与共享包：`frontend:typecheck`、`frontend:test`（22 文件 / 93 项）、`frontend:build`、`contracts:typecheck`、契约测试 34 项、`openspec validate --all`（43 项）与 `docs:build` 全部通过。
- 仓库现状提示：`config/project.json` 与 `config/user.project.json` 自基线提交起被 Git 跟踪，而 README、`.gitignore` 期望与 `test_environment_examples.py` 均要求它们被忽略；该项与诊断功能无关，等待用户决定是否取消跟踪。
- 未启动本机服务、未做浏览器桌面/窄屏体检、未发起真实模型或 CLS 请求；主规格同步与归档等待用户授权。
