# Proposal

## Why

当前诊断仍以串行查询及规则式 `evidence_reasoning` 为主，尚不能完成基于现场证据的多假设因果判断。将交接文档中逐项确认的方案落实为有限预算、可恢复且权限隔离的 LangGraph 闭环，避免把查询命中、兜底报告或模拟结果误称为生产根因确认。

## What Changes

- **BREAKING**：新任务使用 `prepare_context / build_queries / execute_queries / revise_hypotheses / assess_hypotheses / finalize / report`，替换旧节点及强制 SOP-first；保留历史任务展示。
- 实施首轮采证后生成假设、完整评估与增量细化、关系替换、三项根因确认标准；不增加评分、模板依赖、合并或连续无进展检测。
- 使用 5 轮、20 次调用、480 秒及两次内部往返保护，每批和并发初始上限均为 4；诊断模型及工具关闭自动重试，非法节点输出最多修正一次。
- 增加 owner 范围内的一致提交、租约写入保护、预算预占与安全边界恢复，不重放中断外部调用。
- **BREAKING**：统一诊断任务/job 终态及持久化 SSE，诊断 `complete` 仅表示流结束，终态决定成功、失败或取消；聊天流不变。
- 显式隔离固定事故 Mock 快照与默认真实模式，不静默压缩证据或向模型注入评测答案；YAML 项目知识固定快照并直接注入。
- **BREAKING**：新诊断不自动创建案例或知识文档；保留历史案例及独立手动保存入口。
- 程序固定 Markdown 报告结论头部，模型仅组织正文；异常使用程序兜底，不借报告生成重新诊断。

## Capabilities

### New Capabilities

无。复用现有能力，不建立平行诊断、存储或 RAG 系统。

### Modified Capabilities

- `aiops-diagnosis-tasks`：新图、假设闭环、预算、首轮兜底、报告及恢复状态。
- `aiops-evidence-chain`：五类业务数据适配、有效快照、引用边界与一致持久化。
- `api-and-sse-contracts`：类型化调查结果、`change`、新阶段、诊断终止顺序与重连。
- `background-job-runtime`：诊断专用安全恢复、租约校验与终态事务；其他 handler 保持原策略。
- `real-mcp-tools`：诊断无自动重试和显式 Mock 隔离，真实模式不模拟回退。
- `shared-user-project-configuration`：`aiopsDiagnosis`、时间预算及内容文件加载。
- `aiops-diagnosis-ui`：新旧任务、假设和结论呈现、模式标识与终态消费。
- `automated-diagnosis-case-library`：取消新诊断自动沉淀，保留独立案例能力。
- `diagnosis-case-knowledge`：知识保存由显式操作触发，不由新诊断成功触发。

## Impact

- 后端：`aiops/`、`llm/provider.py`、`mcp_client.py`、`mcp_connections.py`、`jobs/runtime.py`、`memory/{repositories,sqlite,extended_sqlite}.py`、`api/app.py`。
- 契约：`packages/api-contracts/src/`；前端：typed client/store、`AiopsEvidenceChain.vue` 和诊断页面。HTTP 路径、统一 envelope、认证和 owner 过滤保持。
- 配置：只在 JSON 模板及加载器中新增分组；本地配置与内容资产不提交真实信息。复用已有 PyYAML，不引入存储服务。
- 本方案优先复用现有 JSON 列，不计划新表；若实施发现必须调整 SQLite schema，必须先说明原因并新增 Alembic revision，不能修改旧迁移。
- 关联依据：`docs/aiops/diagnosis-discussion-handoff.md` 第 4 至 8 节。工程选择集中在 `design.md`，验收与提交边界在 `tasks.md`。

## 审核与授权边界

状态：用户已授权按已确认方案完成可运行、可前端展示的项目，并允许创建功能分支及分阶段本地提交。change 及新增 WIKI 已生成，索引和 Sidebar 已同步。重要取舍再单独确认；不自动推送、合并或改写历史。Git 阶段安排见 `design.md`。

## 规格阶段验证与发布记录

- `openspec validate implement-hypothesis-driven-diagnosis --strict`：通过。
- `openspec validate --all`：43 项通过、0 失败；保留既有主规格 Purpose 过短/占位警告，不顺手修改主规格。
- `npm run docs:build`：包含新增 WIKI 页面的文档构建通过；12 个 include 目标已独立核验，索引与 Sidebar 顺序一致。
- 44 项业务实施任务均未完成，未运行 pytest、前端测试或评测，未创建分支、提交、合并或推送；HEAD 保持 `b94f8bd`。
- 标准 WIKI 发布入口要求 `docs/openspec` 符号链接，但当前是文本占位文件；既有归档要求 `Repository wiki-sync Skill` 未与主规格同步。这两项历史问题保留，未修改链接、脚本、历史页面或主规格。
- 用户纠正此前误触并明确同意“仅发布新增页面”：复用发布脚本的生成函数，仅为本 change 生成 active 页面，使用 `../../../../openspec/` 直接相对 include，同步索引及 Sidebar，并按授权跳过一条历史归档同步问题。12 个引用目标、导航顺序及受保护文件未变化已核验；不将此称为历史 WIKI 全量修复。
