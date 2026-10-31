# Tasks

状态：用户已授权按已确认规格完成项目，并允许新功能分支及分阶段本地提交；不推送、不合并、不改写历史。下列 checkbox 仅在对应实现及验证完成后勾选。阶段对应 `design.md` 的 P1-P6；全部完成后才具备归档条件。

## 1. P1 业务契约与配置

- [ ] 1.1 在共享包定义五类业务结构、嵌套字段、状态、next_step/query_plan 和可选 diagnosis 投影；验证 package 契约测试覆盖字段集合、空列表、nullable 及 change。
- [ ] 1.2 增加严格后端节点模型与引用/完整集合校验，保留评估不写 statement 的边界；新增模型测试覆盖多余字段、重复/遗漏 ID、非法引用、竞争反向重复和非法结论/路由。
- [ ] 1.3 实现 aiopsDiagnosis JSON 加载、默认 real 与已定预算，同步两份模板；配置测试覆盖递归覆盖、缺分组默认、布尔值冒充整数、非法阶段总和，模板不得包含真实凭据。
- [ ] 1.4 更新共享 OpenAPI 的可选调查结果、新阶段和 stream cursor 描述，不改既有路径/envelope；契约测试验证 401/403、历史无新字段及诊断/聊天事件兼容。
- [ ] 1.5 补充配置与接口说明，明确目标与现状；运行 `npm run contracts:typecheck`、`npm --workspace packages/api-contracts run test` 及目标模型/配置 pytest 后核对文档字段。

## 2. P2 事务、预算状态与安全恢复

- [ ] 2.1 增加 Repository 的 reserve/query/node/finish 一致提交 Protocol 及 SQLite 实现；事务故障注入测试验证任一步失败整次回滚，禁止领域代码直接操作 session。
- [ ] 2.2 实现安全领取、租约有效性与 claim 代次写入校验；并发测试覆盖两个 worker 竞争、旧 worker 迟到、过期同 worker ID，验证不能重复 dispatch 或覆盖结果。
- [ ] 2.3 实现持久调用 intent、预算预占、实际发起计数与 unknown 占用；测试覆盖预占前/后、实际发起前/后崩溃、可证明未发起释放、同批只计一轮。
- [ ] 2.4 保存 current state/last valid assessment/next_node 及稳定提交身份，原始数据仅存证据并解引用；测试验证节点/查询重入幂等、关系失效与完整结果恢复。
- [ ] 2.5 扩展 BackgroundJobContext 的执行者信息及诊断已提交终态识别；测试验证 Runtime 不二次标成功/失败/取消，其他 handler 原有重试策略不变。
- [ ] 2.6 实现失租后停写/停调用，租约恢复进入已保存阶段；恢复测试覆盖工具不重放、核心模型中断程序失败收尾、报告中断兜底和截止时间不重置。
- [ ] 2.7 一致协调 queued/running 取消与终态提交；测试覆盖排队取消不加载外部资源、并发取消、已终态取消拒绝和真实 partial 返回保留。
- [ ] 2.8 为诊断显式 retry 新建 task/job 保留旧终态，其他 retry 保持；API/权限测试覆盖非 owner、失败/取消重试及旧报告不改写，不引入自动重试。
- [ ] 2.9 更新恢复、预算不确定和终态文档；运行目标 Repository/Runtime 测试及 `test_extended_capabilities.py`、`test_memory_repositories.py`、`test_memory_migrations.py`。如必须改 schema，先取得具体迁移确认再新增 revision 和升级测试。

## 3. P3 上下文与隔离工具

- [ ] 3.1 实现 YAML safe_load、路径解析与固定知识/目录快照；测试覆盖空路径、缺失/非法文件、文件中途变化及恢复不重读，不给知识分配现场 evidence_id。
- [ ] 3.2 提供空知识模板及忽略私有知识的规则，文档说明内容不是应用配置；测试确保模板无编造实际事实和敏感内容。
- [ ] 3.3 增加独立事故场景格式与固定时间快照，只含告警/日志/指标/变更；场景测试验证同对象/时间一致、无答案字段，不引用旧 eval_fixtures/eval_results。
- [ ] 3.4 注入 Mock SearchLog/QueryMetric/QueryChange 筛选实现；测试覆盖时间范围、服务/实例/指标、未知参数/语法、空结果、干扰数据，改变窗口不移动异常。
- [ ] 3.5 按用户已启用真实连接发现工具，真实缺指标/变更明确未满足需求；测试验证默认 real、Mock 必须显式场景、真实失败不模拟回退、owner 与同名工具保护。
- [ ] 3.6 建立诊断专用 LLM/MCP 无自动重试策略与阶段超时；用传输替身验证实际底层请求次数为一次，修正请求失败也不重试，聊天/连接管理设置不被覆盖。
- [ ] 3.7 实现差异化参数构建和重复失败调用校验；测试覆盖首轮范围、跨服务合理扩查、指标白名单/维度、变更一级依赖及新信息补查说明。
- [ ] 3.8 更新真实/Mock 操作说明与知识示例，运行目标上下文/工具测试、`test_evidence_tools.py`、`test_mcp_observability.py`、`test_llm_provider.py`；不发真实外部查询或运行新评测。

## 4. P4 假设图、报告和持久 SSE

- [ ] 4.1 实现 prepare/build/execute/revise/assess/finalize/report 七节点及 START 恢复条件边；图测试验证首轮先采证、后续三个动作及未知动作拒绝，无新模型路由节点。
- [ ] 4.2 实现 revise 增量应用及程序 ID，prompt 明确细化/更换原因和非事实知识；测试验证 pending 初始化、未修改项保留、关系/结论失效及不合并假设。
- [ ] 4.3 实现 assess 完整判断、关系替换、重开、事故结论和 next_step；脚本化模型测试覆盖具体因果、症状不足、竞争解释、关键反证、共同因素及不按评分确认。
- [ ] 4.4 实现 query_plan 两列表、未满足需求传递及一次针对性修正；测试覆盖部分可查、双空非法、超额不裁剪、错误参数、无调用回流及首轮不预生成假设。
- [ ] 4.5 实现有界并发和逐调用一致落盘，批末统一分析；测试验证实际并发上限、批次分波仍一轮、单失败不取消其他、依赖调用在后批、未发起不写 failed 查询。
- [ ] 4.6 实现可注入时钟、5/20/2 预算及阶段截止；测试覆盖第 5 轮结果分析、最后内部评估、工具更严格并发、剩余 15 秒超时、390/450/480 边界及恢复等待消耗时间。
- [ ] 4.7 实现首轮全失败/全空/合法空假设最低退出；测试区分初始化 failed/null、真实停止事实 succeeded/unconfirmed，以及部分成功仍继续。
- [ ] 4.8 实现 finalize 未决转 unresolved、保留理由与缺口及真实停止事实；测试禁止预算自动反驳/确认、单失败推定永久缺口和取消请求改写已提交终态。
- [ ] 4.9 实现 Markdown 权威头部、四部分正文及程序兜底，Report 不自动案例入库；测试覆盖模型正文失败、历史快照隔离、未分析结果、Mock 标识、条件性建议及无新知识/索引副作用。
- [ ] 4.10 实现诊断统一 finish、稳定 SSE ID、report/error/status/complete 顺序与 Last-Event-ID；后端合同测试覆盖失败有报告、取消、空游标、跨 job 游标、重连、EOF 不合成成功及事件幂等。
- [ ] 4.11 更新后端图/诊断操作与兼容文档，迁移旧 diagnostics 测试以保留仍适用断言并新增替换行为测试；运行目标诊断/恢复/SSE pytest、`uv run ruff check .`、`uv run pyright`，不删除测试或放宽 strict。

## 5. P5 前端新旧兼容

- [ ] 5.1 typed client/store 支持 diagnosis 投影和新阶段，历史数据使用原解析；`aiopsStore.test.ts` 覆盖未知/旧节点、不伪造假设、回载错误不展示过时成功结果。
- [ ] 5.2 aiops parser 保持 error 后消费至 complete、事件 ID 去重与 cursor；client/store 测试覆盖失败有报告、重连重复、无 complete EOF、取消，聊天 SSE 消费行为不变。
- [ ] 5.3 AiopsEvidenceChain 显示全部合法/未知阶段、假设/关系/依据/缺口，保留默认折叠工具和主区报告；`aiopsComponents.test.ts` 验证旧节点兼容及不重复报告正文。
- [ ] 5.4 显示事故确认与任务终态的区别、Mock 标签及历史判断局限；组件测试验证 supported 不自动 confirmed、兜底不掩盖 failed、历史未知模式不标真实。
- [ ] 5.5 保留反馈、手动知识保存、桌面内部滚动及窄屏纵向布局；`aiopsLayout.test.ts` 覆盖无页面横向溢出，真实浏览器验收另须明确授权，不使用伪造生产数据。
- [ ] 5.6 同步中文界面/使用说明；运行 `npm run frontend:typecheck`、`npm run frontend:test`、`npm run frontend:build`，UI 验收获授权后提供桌面与窄屏截图。

## 6. P6 联合验收与规格对齐

- [ ] 6.1 增加集成测试贯通固定 Mock 场景、真实工具传输替身、任务/job/SSE 和前端回载；验证成功确认、正常未确认、初始化失败、模型失败、取消、恢复不重放七类主路径，不运行旧评测。
- [ ] 6.2 完成跨 owner API/Repository/引用/游标及脱敏集成测试；验证本地配置、日志、token 与云凭据不出现在事件、报告、测试固化或 Git diff 中。
- [ ] 6.3 回归聊天、知识检索/索引、MCP 管理及独立案例保存；运行后端 `uv run pytest`、`uv run ruff check .`、`uv run pyright` 与前端/共享包全套验证，失败保留原因，不 skip 或删断言。
- [ ] 6.4 按实际完成状态同步 README、配置和运行说明；验证新旧入口、模式、时间、报告/错误行为与代码一致，不声明未接入真实指标/变更已完成。
- [ ] 6.5 核对全部 delta 与主规格的适用边界，准备审批后的同步/归档清单；运行 `openspec validate --all` 与 `npm run docs:build`，所有上述实现任务完成后再请用户确认。

## 验收映射

| 已确认专题 | 主要任务 |
|---|---|
| 任务中断恢复 | 2.1-2.9、4.1、4.6、4.10、6.1 |
| 诊断无自动重试 | 3.5-3.7、4.4、6.1 |
| Mock 同事故与隔离 | 3.1-3.5、4.9、5.4 |
| 首轮最低兜底 | 4.4、4.7、4.8 |
| 一致终态/SSE | 2.5-2.8、4.9-4.10、5.2、6.1 |
| 更新及兼容契约 | 1.1-1.4、2.4、4.2-4.3、5.1-5.5 |
| SOP、案例与配置收口 | 1.3、3.1-3.2、4.9、6.3-6.5 |

## Workflow follow-up

- 用户已确认整体方案并授权新分支及分阶段本地提交；重要范围、权限或架构取舍再单独确认，不逐项请求实施审批。
- 授权后基于重新核验的 b94f8bd 创建 feature/hypothesis-driven-diagnosis，先保存规格与 WIKI，再按 P1-P6 分阶段新提交；逐文件 staging，不包含本地配置、缓存或评测产物。
- 所有 tracked tasks 验证完成并获归档授权后，同步主规格并归档 change，再运行 publish-openspec-wiki 的 archive 流程及 docs 构建。归档不是本期尚未完成的实施任务勾选依据。
- 不自动 merge、push、PR、amend 或强制改写历史；回退只在明确授权后使用新 revert commit 并保留数据。
