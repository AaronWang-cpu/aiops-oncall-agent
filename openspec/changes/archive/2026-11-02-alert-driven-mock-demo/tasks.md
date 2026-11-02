# 任务：告警驱动的模拟演示

## P1 后端：告警入口与场景

- [x] `MockScenario` 由单个 `alert` 改为 `alerts` 列表（至少 1 条），`ScenarioAlert` 增加 `name`、`severity`
- [x] `_alert()` 按请求 service 匹配场景告警，匹配不到时取第一条
- [x] 新增 `mock_alerts.ScenarioAlertProvider` 把场景告警映射为 `ActiveAlert`
- [x] `_active_alert_provider` 在 mock 模式使用场景告警源，real 模式仍走 Prometheus/Alertmanager
- [x] 现有两个场景文件迁移为 `alerts` 列表
- [x] 新增 `checkout-peak-incident.json` 演示场景（3 条告警 + 决定性证据 + 干扰项）

## P2 后端：知识进入提示词与评估契约

- [x] `_background_hint()` 把项目概述与告警服务及其一级依赖说明拼成「项目背景（不构成证据）」段落
- [x] 把背景段落注入 `build_queries`、`revise_hypotheses`、`assess_hypotheses` 三个提示词
- [x] 无知识时不产生任何背景段落
- [x] `assess_hypotheses` 提示词穷举 `hypothesis_status` 取值枚举
- [x] 新增本地项目知识 `config/aiops-project-knowledge.yaml`（被 Git 忽略）
- [x] 后端测试补充场景告警源、背景注入与枚举契约

## P3 前端：收敛工作区与重排诊断页

- [x] 删除手工诊断入口 `AiopsRunForm.vue`，诊断只能从告警发起
- [x] 删除 `AiopsCaseLibrary.vue`、`AiopsLedgerPanel.vue`、`McpView.vue`、`stores/mcp.ts`、`mcp/mcpClient.ts`
- [x] 删除路由 `/mcp` 与侧栏「MCP 连接」入口
- [x] 诊断页重排为左列来源（活跃告警 + 诊断历史）与右列单列滚动
- [x] 取消检查器分页，结论/证据/执行链/报告在右列顺序呈现
- [x] 执行链随右列统一滚动，修复被固定高度网格裁剪的问题
- [x] 工作台标题改为「AIOps 诊断台」
- [x] store 清理案例与保存相关状态，`refreshCollections` 收敛为 `refreshHistory`

## P4 验证与规格

- [x] 后端相关测试通过
- [x] 前端类型检查、单元测试与构建通过
- [x] mock 模式手工验证活跃告警、执行链滚动与报告
- [x] 同步 OpenSpec 规格并归档本次变更
