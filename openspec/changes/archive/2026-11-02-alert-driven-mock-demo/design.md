# 设计：告警驱动的模拟演示

## Context

真实模式的活跃告警来自 Prometheus/Alertmanager 聚合（`_active_alert_provider`），前端把它作为唯一诊断入口。模拟模式此前把一条 `alert` 直接写进 `MockScenario`，既不经过活跃告警 provider，也没有多告警概念，于是演示时缺少“选告警”这一步。

项目知识在 `prepare_context` 固定快照后，只被列进 payload 的服务名，没有进入 `build_queries` / `revise_hypotheses` / `assess_hypotheses` 的提示词。知识“直接注入”的意图没有落地。

`assess_hypotheses` 的输出契约要求 `hypothesis_status`，但提示词没有列出取值，模型编造非法值后结构校验失败，整条链路以核心阶段失败收尾。

前端上一轮收敛后仍保留手工诊断入口、案例库、调查账本与 MCP 连接页，与“从告警发起、围绕证据判读”的工作区目标不符。

## Goals

- 让 mock 与 real 在入口上完全一致：先看活跃告警，再从一条确定的告警发起诊断。
- 让固定的项目知识真正进入推理，同时保持它是背景而非证据。
- 让评估阶段的结构契约对模型可穷举，避免可预期的整链失败。
- 让前端工作区只围绕告警处理：选告警、看过程、读结论/证据/报告。

## Non-Goals

- 不改真实告警聚合、诊断算法、预算默认值与持久化结构。
- 不为被删除的前端板块保留隐藏入口或兼容开关。
- 不引入图表库、新 UI 依赖或新的运行时配置项。

## Decisions

1. **mock 告警源读场景文件，而不是新增配置项或外部进程**：`ScenarioAlertProvider` 直接复用 `aiopsDiagnosis.mockScenarioPath` 指向的同一份场景快照，把其中 `alerts` 映射成 `ActiveAlert`。这样 mock 模式不需要额外进程、额外配置项或第二份告警 fixture，场景文件仍是唯一事实来源；`_active_alert_provider` 只按 `mode` 分流，real 模式完全不受影响。

2. **知识作为背景而不是证据**：`_background_hint()` 把 `project_overview` 与「告警服务 + 其一级依赖」的服务说明拼成一段显式标注「用于理解服务职责与术语，不构成证据」的文字，注入三个推理提示词。知识仍然只是提示词上下文，不产生 `evidence_id`、不进入证据链；没有知识时不产生任何段落，行为与之前一致。

3. **场景由单告警改多告警：接受旧检查点不再恢复**：`MockScenario` 由 `alert` 改为 `alerts`（`min_length=1`），`_alert()` 按 service 匹配、匹配不到取第一条。兼容取舍是：旧运行里持久化的 `context.scenario.alert` 形状不再被 `_content()` / `_scenario()` 识别为场景告警——`restore_diagnosis_context` 会因缺 `alerts` 校验失败而回退为无场景。我们选择接受这一取舍，而不是为旧形状写迁移或双读逻辑：模拟场景属于本地演示资产，重跑即可，维护两套形状的成本高于收益。

4. **在提示词里穷举枚举，而不是新增枚举归一化映射**：与其在后端加一层“把模型给的非法状态映射成合法值”的兜底（会掩盖模型输出错误，也让校验形同虚设），选择在 `assess_hypotheses` 提示词里直接列出 `pending、investigating、supported、contradicted、blocked、unresolved`。让模型一次给出合法值，保留“非法输出即失败并收尾”的既有契约。

5. **前端取消检查器分页，改单列滚动**：结论与假设、现场证据、执行链与报告本就是“同一任务的判读材料”，分页让每一屏只承担一件事的代价是频繁切换与信息割裂。改为右列单列滚动后，operator 顺序读完即可，减少交互面。

6. **执行链滚动由父级滚动容器承担**：执行链此前位于固定高度网格内、被 `overflow: hidden` 裁剪且没有自己的滚动容器，导致内容多时无法滚动。改为让右列（`aiops-workbench__primary`）作为统一滚动容器，执行链随列一起滚动，而不是给每个子块各自加滚动条。

## Risks

- 删除 /mcp 前端页会让连接管理在界面层不可演示：已确认属于本次取舍，后端接口保留，其他客户端仍可使用。
- 旧检查点不恢复为场景告警：仅影响未重跑的旧 mock 运行，重跑即得到新版行为。
- 单列滚动可能让长报告与执行链“看起来很长”：接受，因为信息不再被分页藏起来，且截断/滚动范围在各自区域显式表达。

## Migration Plan

1. 后端：`MockScenario` 改 `alerts` 列表并新增 `ScenarioAlertProvider`，在 `_active_alert_provider` 按 mode 分流。
2. 后端：`_background_hint()` 注入推理提示词，`assess_hypotheses` 提示词补齐状态枚举。
3. 内容：新增 `checkout-peak-incident.json` 演示场景与本地项目知识（被忽略，不提交）。
4. 前端：删除手工入口、案例库、账本、MCP 页与相关 store/客户端，重排为两栏，修正执行链滚动，改品牌文案。
5. 同步 OpenSpec 规格并归档本次变更。

## Verification

- 后端：`pytest apps/backend/tests/test_active_alerts.py apps/backend/tests/test_diagnosis_context.py apps/backend/tests/test_diagnosis_graph.py`。
- 前端：`npm run frontend:typecheck`、`npm run frontend:test`、`npm run frontend:build`。
- 手工：mock 模式打开 `/aiops`，确认活跃告警来自场景、可从告警发起诊断、执行链可滚动、报告可读。
- `openspec validate 2026-11-02-alert-driven-mock-demo --strict`、`openspec validate --all`。
