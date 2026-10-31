## ADDED Requirements

### Requirement: Diagnosis configuration uses merged JSON
诊断 SHALL 从既有 merged project.json/user.project.json 的 aiopsDiagnosis 分组读取模式、路径与预算，不从环境变量或第二套应用配置读取。模板默认 real，无分组的旧配置使用安全默认；显式非法值 MUST 明确失败。

#### Scenario: User overrides diagnosis budgets
- **WHEN** user.project.json 覆盖分组中的部分字段
- **THEN** MUST 递归合并其余默认，校验正整数、模式及阶段总和，布尔值不得作为整数通过。

#### Scenario: Mock mode is not explicit
- **WHEN** 未配置 Mock 或模板未填写场景
- **THEN** MUST 保持 real，不因开发环境、缺凭据或工具失败自动启用 Mock。

#### Scenario: Local personal content is prepared
- **WHEN** 操作者配置知识或场景文件
- **THEN** MUST 不提交本地凭据、真实日志或项目私有知识，模板只包含空/明确模拟内容。

### Requirement: Fixed project knowledge snapshot
任务 SHALL 在首次开始时读取并固定完整项目知识、目录与场景依据。知识 YAML 使用 project_overview、services 及 description，知识不得变成事故事实或 evidence_id；小型知识直接注入，不新增 RAG 或裁剪。

#### Scenario: Knowledge file changes during investigation
- **WHEN** 操作者在任务中途修改文件或服务重启
- **THEN** 同次调查 MUST 使用原快照，不重新读取来改变依据。

#### Scenario: Knowledge path is absent
- **WHEN** 未配置知识路径
- **THEN** MUST 允许空知识并如实体现信息缺失，不要求模型补写。

#### Scenario: Explicit knowledge path is invalid
- **WHEN** 已配置文件缺失或 YAML 结构非法
- **THEN** MUST 明确报准备阶段错误并程序兜底，不静默使用空知识，也不执行外部工具。

### Requirement: Diagnosis time budget configuration
诊断 SHALL 初始采用 investigationSeconds=390、finalAnalysisSeconds=60、reportSeconds=30、totalSeconds=480，工具和模型单次上限 60 秒。阶段之和 MUST 等于总时长，超时仍受连接配置及阶段剩余时间限制。

#### Scenario: Phase allocation is invalid
- **WHEN** 秒数非正整数或阶段总和不同于总时长
- **THEN** MUST 拒绝配置，不通过自动延长、缩短或恢复重置掩盖错误。

#### Scenario: Exploration has fifteen seconds left
- **WHEN** 新请求在探索截止前只剩 15 秒
- **THEN** MUST 以不超过阶段剩余时间的超时执行，不授予完整 60 秒。
