# 告警驱动的模拟演示

## Why

模拟模式下的告警入口与真实模式不一致。真实模式通过 Prometheus/Alertmanager 聚合出活跃告警，operator 选择一条告警即可发起诊断；模拟模式此前只有一条写死在场景里的 `alert`，既不进入活跃告警列表，也没有可点击的告警条目。演示时运维人员无法走“选告警 → 发起诊断”的同一条路径，模拟模式与真实模式在入口处就分叉，掩盖了真实链路的可用性。

项目知识此前只在 `prepare_context` 的 payload 里列了服务名，从未进入任何提示词或证据链。也就是说“把项目知识作为背景提供”这一能力实际上从未生效：模型看不到服务职责与术语，只能凭告警字面推断，项目知识既没有帮助推理，也没有被明确约束为“不构成证据”。

`assess_hypotheses` 的提示词没有列出 `hypothesis_status` 的合法取值，模型会编造非法状态，导致结构校验失败并以核心阶段执行失败收尾。真实故障记录为 `assess_hypotheses output stayed invalid: 结构校验失败，字段：hypothesis_assessments.0.hypothesis_status...` 一次未列枚举的疏漏会让整条诊断链路失败。

前端在上一轮收敛后仍保留了与告警处理无关的人员：手工诊断入口、案例库、调查账本与 MCP 连接页。它们要么已被告警驱动的入口取代，要么属于后端能力（接口保留、前端不再需要），继续留在工作区里只会扩大维护面积并让页面重新变臃肿。

## What Changes

- 后端把 `MockScenario` 由单个 `alert` 改为 `alerts` 列表（至少 1 条），`ScenarioAlert` 增加 `name` 与 `severity`；`_alert()` 按请求里的 service 匹配场景告警，匹配不到时取第一条。
- 新增 `mock_alerts.ScenarioAlertProvider`，把场景告警映射为 `ActiveAlert`（`source=local-scenario`、`status=active`）。`api/app.py` 的 `_active_alert_provider` 在 `aiopsDiagnosis.mode == "mock"` 时使用它，real 模式仍走 Prometheus/Alertmanager 聚合；不需要额外进程或新增配置项。
- 项目知识真正进入提示词：`_background_hint()` 把 `project_overview` 与「告警服务 + 其一级依赖」的服务说明拼成「项目背景（用于理解服务职责与术语，不构成证据）」段落，注入 `build_queries`、`revise_hypotheses`、`assess_hypotheses` 三个提示词；没有知识时不产生任何段落。
- `assess_hypotheses` 提示词补齐 `hypothesis_status` 的取值枚举（pending、investigating、supported、contradicted、blocked、unresolved）。
- 新增演示场景 `checkout-peak-incident.json`：1 个场景、3 条告警（order-service 连接池上限被配置变更从 100 下调到 20；payment-service 因 fraud-detection-service 新版规则链导致风控检查超时；inventory-service v3.0.0 重构库存锁引入死锁重试），每条告警都有同窗口内的决定性变更记录、决定性日志与关键指标，并含自我排除型干扰项。新增本地项目知识 `config/aiops-project-knowledge.yaml`（被 Git 忽略，只写服务职责等平稳背景）。
- 本地未跟踪配置把 `llm.timeoutSeconds`、`aiopsDiagnosis.modelTimeoutSeconds` 调到 300，`finalAnalysisSeconds` 调到 180，`totalSeconds` 630（仓库内 `project.template.json` 默认值未改）。
- 前端删除手工诊断入口 `AiopsRunForm.vue`，诊断只能从一条确定的告警发起。
- 前端删除 `AiopsCaseLibrary.vue`、`AiopsLedgerPanel.vue`、`McpView.vue`、`stores/mcp.ts` 与 `mcp/mcpClient.ts`；路由 `/mcp` 与侧栏「MCP 连接」入口一并删除，侧栏只剩「智能诊断」；后端 MCP/案例接口保持不变。
- 诊断页重排为两栏：左列「活跃告警 + 诊断历史」，右列单列滚动（任务卡 → 时间线 → 结论与假设 → 现场证据 → 执行链 → 报告），未选中任务时显示一句操作提示；`≤1024px` 改为整页纵向滚动。此前检查器分页（结论/证据/账本三个 tab）被取消。
- 修复执行链无法滚动的问题：执行链现在位于右列的统一滚动区域内，整列可鼠标滚动。
- 工作台标题由「Super AI 智能工作台」改为「AIOps 诊断台」（侧栏品牌与页头）。
- store 清理：删除 `diagnosticCases`、`savedCaseDocumentId`、`reloadDiagnosticCases`、`refreshDiagnosticCases`、`saveActiveCase`，`refreshCollections` 收敛为 `refreshHistory`。

## Capabilities

- `active-alert-subscription-entry`（mock 模式的活跃告警取自场景文件，且成为唯一诊断入口）
- `real-mcp-tools`（Mock 场景快照改为多告警列表）
- `aiops-diagnosis-tasks`（评估器提示词穷举假设状态枚举）
- `shared-user-project-configuration`（项目知识作为背景注入推理提示词）
- `aiops-diagnosis-ui`（告警驱动入口与两栏布局，移除账本）
- `vue-app-shell`（移除 `/mcp` 路由与入口）
- `chinese-ai-workspace-experience`（工作台品牌与单一工作区）
- `mcp-connection-management`（移除前端 MCP 管理工作区）
- `automated-diagnosis-case-library`（移除前端案例库展示）

## Impact

- 后端：`MockScenario` / `ScenarioAlert` 结构、mock 活跃告警来源、诊断提示词组装；`api/app.py` 的活跃告警 provider 选择。
- 前端：路由、侧栏导航、诊断页布局、诊断 store；删除若干组件、视图与客户端。
- 不新增或修改任何 HTTP 端点、共享契约字段与持久化结构；后端 MCP、案例与对话/知识接口保持可用。
- 已存在的旧检查点（`context.scenario.alert` 形状）不再恢复为场景告警：mock 活跃告警入口只对配置了新版 `alerts` 列表场景的运行生效。

## Out of Scope

- 不改任何后端 HTTP 端点、共享契约与数据库结构。
- 不删除后端 MCP、案例、对话与知识库相关代码与测试。
- 不改真实模式的告警聚合、诊断算法与预算默认值（仓库内模板默认值不变）。
- 不为被删除的前端板块保留隐藏入口。
