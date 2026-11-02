# shared-user-project-configuration Specification

## Purpose
TBD - created by archiving change extract-user-config-and-chat-assets. Update Purpose after archive.

## Requirements

### Requirement: Merged user project configuration
系统 SHALL 将基础项目配置文件与用户项目配置文件合并为运行时项目配置，基础文件提供通用默认值，用户文件只覆盖每个使用者不同的字段。

#### Scenario: User config overrides nested fields
- **WHEN** 基础配置包含通用 `llm`、`clsMcpServer` 和 `clsLogUpload` 对象，用户配置只包含这些对象中的部分字段
- **THEN** 配置加载器 MUST 递归合并对象，并让用户配置中的字段覆盖基础配置中的同路径字段。

#### Scenario: Arrays and scalar values are replaced
- **WHEN** 用户配置覆盖数组、字符串、数字或布尔值
- **THEN** 配置加载器 MUST 使用用户配置值整体替换基础配置值。

#### Scenario: Missing user config keeps base defaults
- **WHEN** 用户配置文件不存在或不包含某个字段
- **THEN** 配置加载器 MUST 使用基础配置中的值，并且 MUST NOT 从本机环境变量补充项目配置。

### Requirement: Personal configuration field extraction
本地基础配置 SHALL 提供通用默认值，本地 user 配置 SHALL 提供每个使用者不同的实际开发值，两个运行时配置文件均不得被版本控制跟踪。

#### Scenario: Extracted personal fields are empty in templates
- **WHEN** 检查 `config/project.template.json` 和 `config/user.project.template.json`
- **THEN** API key、云凭据、密码和真实 CLS 资源 ID MUST 为空字符串

#### Scenario: Runtime loads personal fields from ignored user config
- **WHEN** 应用默认加载项目配置
- **THEN** 运行时配置 MUST 从被忽略的本地 `config/project.json` 和 `config/user.project.json` 合并读取，MUST NOT 从环境变量或受版本控制模板直接读取实际凭据

#### Scenario: Local configuration is missing
- **WHEN** 新克隆尚未创建本地配置
- **THEN** 启动文档 MUST 提供从两个模板复制并填写配置的明确命令

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
任务 SHALL 在首次开始时读取并固定完整项目知识、目录与场景依据。知识 YAML 使用 project_overview、services 及 description，知识不得变成事故事实或 evidence_id；小型知识直接注入，不新增 RAG 或裁剪。固定的知识 MUST 作为标注「不构成证据」的项目背景段落注入查询规划、假设调整与假设评估的推理提示词，覆盖项目概述与「告警服务及其一级依赖」的服务说明，且 MUST NOT 制造 evidence_id 或进入证据链。

#### Scenario: Knowledge file changes during investigation
- **WHEN** 操作者在任务中途修改文件或服务重启
- **THEN** 同次调查 MUST 使用原快照，不重新读取来改变依据。

#### Scenario: Knowledge path is absent
- **WHEN** 未配置知识路径
- **THEN** MUST 允许空知识并如实体现信息缺失，不要求模型补写，也不产生任何项目背景段落。

#### Scenario: Explicit knowledge path is invalid
- **WHEN** 已配置文件缺失或 YAML 结构非法
- **THEN** MUST 明确报准备阶段错误并程序兜底，不静默使用空知识，也不执行外部工具。

#### Scenario: Knowledge reaches the reasoning prompts
- **WHEN** 配置了项目知识且开始诊断
- **THEN** 查询规划、假设调整与假设评估的提示词 MUST 包含标注「不构成证据」的项目背景段落，含项目概述与相关服务说明；该背景 MUST NOT 作为 evidence_id 或证据条目出现。

#### Scenario: Knowledge block stays absent without knowledge
- **WHEN** 没有配置项目知识
- **THEN** MUST NOT 在这些提示词中产生任何项目背景段落。

### Requirement: Diagnosis time budget configuration
诊断 SHALL 初始采用 investigationSeconds=390、finalAnalysisSeconds=60、reportSeconds=30、totalSeconds=480，工具和模型单次上限 60 秒。阶段之和 MUST 等于总时长，超时仍受连接配置及阶段剩余时间限制。

#### Scenario: Phase allocation is invalid
- **WHEN** 秒数非正整数或阶段总和不同于总时长
- **THEN** MUST 拒绝配置，不通过自动延长、缩短或恢复重置掩盖错误。

#### Scenario: Exploration has fifteen seconds left
- **WHEN** 新请求在探索截止前只剩 15 秒
- **THEN** MUST 以不超过阶段剩余时间的超时执行，不授予完整 60 秒。
