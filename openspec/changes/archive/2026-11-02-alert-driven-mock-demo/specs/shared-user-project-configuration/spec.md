## MODIFIED Requirements

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
