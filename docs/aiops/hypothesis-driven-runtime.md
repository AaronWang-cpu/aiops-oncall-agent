# 假设驱动诊断运行说明

关联变更：[implement-hypothesis-driven-diagnosis](/changes/active/implement-hypothesis-driven-diagnosis/)。

## 实施状态

本页随实现更新，不把已确认设计当作已完成能力：

| 阶段 | 状态 |
|---|---|
| P1 业务模型、共享契约和配置 | 阶段验收通过；未切换诊断入口 |
| P2 一致持久化与恢复 | 持久底座和恢复策略验收通过；新图接线仍在 P4 |
| P3 固定上下文与隔离工具 | 未开始 |
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

## 持久恢复边界

checkpoint 保存 runtime、working_state 和 last_valid_assessment；原始工具结果仅存证据，通过当前用户、当前任务的引用回载完整数据，不用摘要恢复推理。

调用前先持久保存 intent 和预算预占。只有明确知道已发起时才保存实际调用计数；恢复时，未确定发起的预占转为 unknown 保守占用，已明确发起但未提交结果的调用保留实际计数及轮次，不退还额度。恢复不重发原调用，中断查询保存失败说明，不作为假设反证。

`plan_diagnostic_recovery` 仅分类已保存阶段和中断状态，不调用模型或工具。已提交节点从 next_node 继续；核心模型意图中断进入程序失败收尾，报告模型中断使用程序兜底。UTC 截止和已保存剩余时间不重置，停机等待扣除预算，390/450/480 秒之后仅允许对应阶段工作。

Runtime 支持诊断专用 on_termination 回调，统一处理取消、watchdog 超时及未提交终态的 handler 返回；不会覆盖已提交诊断终态。终态持久化不可用时保留可恢复 job，不单独宣布成功。回调和恢复策略接入新七节点及最终 Markdown 生成属于 P4，当前默认入口仍为旧图。
