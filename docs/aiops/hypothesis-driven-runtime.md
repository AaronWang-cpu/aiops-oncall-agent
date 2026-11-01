# 假设驱动诊断运行说明

关联变更：[implement-hypothesis-driven-diagnosis](/changes/active/implement-hypothesis-driven-diagnosis/)。

## 实施状态

本页随实现更新，不把已确认设计当作已完成能力：

| 阶段 | 状态 |
|---|---|
| P1 业务模型、共享契约和配置 | 阶段验收通过；未切换诊断入口 |
| P2 一致持久化与恢复 | 持久底座和恢复策略验收通过；新图接线仍在 P4 |
| P3 固定上下文与隔离工具 | 上下文与工具适配器验收通过；七节点调用在 P4 接线 |
| P4 假设图、预算与报告 | 未开始 |
| P5 前端展示与兼容 | 未开始 |
| P6 联合验收与本机启动 | 未开始 |

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

## 持久恢复边界

checkpoint 保存 runtime、working_state 和 last_valid_assessment；原始工具结果仅存证据，通过当前用户、当前任务的引用回载完整数据，不用摘要恢复推理。

调用前先持久保存 intent 和预算预占。只有明确知道已发起时才保存实际调用计数；恢复时，未确定发起的预占转为 unknown 保守占用，已明确发起但未提交结果的调用保留实际计数及轮次，不退还额度。恢复不重发原调用，中断查询保存失败说明，不作为假设反证。

`plan_diagnostic_recovery` 仅分类已保存阶段和中断状态，不调用模型或工具。已提交节点从 next_node 继续；核心模型意图中断进入程序失败收尾，报告模型中断使用程序兜底。UTC 截止和已保存剩余时间不重置，停机等待扣除预算，390/450/480 秒之后仅允许对应阶段工作。

Runtime 支持诊断专用 on_termination 回调，统一处理取消、watchdog 超时及未提交终态的 handler 返回；不会覆盖已提交诊断终态。终态持久化不可用时保留可恢复 job，不单独宣布成功。回调和恢复策略接入新七节点及最终 Markdown 生成属于 P4，当前默认入口仍为旧图。
