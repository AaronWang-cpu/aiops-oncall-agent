# 假设驱动诊断运行说明

关联变更：[implement-hypothesis-driven-diagnosis](/changes/active/implement-hypothesis-driven-diagnosis/)。

## 实施状态

本页随实现更新，不把已确认设计当作已完成能力：

| 阶段 | 状态 |
|---|---|
| P1 业务模型、共享契约和配置 | 阶段验收通过；未切换诊断入口 |
| P2 一致持久化与恢复 | 未开始 |
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
