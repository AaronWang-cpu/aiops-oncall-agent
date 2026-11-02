## MODIFIED Requirements

### Requirement: Hypothesis assessment and root cause confirmation
诊断 SHALL 完整更新全部当前假设及关系，分别判断假设状态、事故级确认和下一动作。确认 MUST 同时具备具体原因、因果链证据、无关键反证或主要未决竞争解释；现有工具无法观测的内部实现（数据库内核、网络链路、第三方服务内部）本身不构成未决竞争解释，已观测机制能解释全部症状且无反证时 MUST 确认并把无法观测的疑问写入 gaps；不得以数值评分或单个 supported 自动确认。评估器提示词 MUST 穷举允许的 hypothesis_status 取值（pending、investigating、supported、contradicted、blocked、unresolved），非法取值 MUST 作为结构校验失败处理，不得静默映射为合法状态。

#### Scenario: Supported symptom is not a confirmed cause
- **WHEN** 证据仅支持连接池耗尽但不能解释为何耗尽
- **THEN** 系统 MUST 保持具体根因未确认，root_cause 为 null，并说明必要机制缺口。

#### Scenario: Existing explanation is refined
- **WHEN** 细化同一原因解释
- **THEN** 系统 MUST 保留 ID、重置该解释判断为 pending、失效当前旧关系与事故结论，并用已有证据重新评估；更换原因必须新增 ID。

#### Scenario: Investigation ends with unresolved hypotheses
- **WHEN** 整体调查结束
- **THEN** pending、investigating、blocked MUST 转 unresolved 并保留理由和缺口，supported/contradicted 不因结束而改变。

#### Scenario: New evidence warrants reopening
- **WHEN** 调查进行中新证据或阻碍解除改变旧判断
- **THEN** 系统 MUST 允许有依据地重新评估，并说明原因；整体终态后不得改写该次调查。

#### Scenario: Assessment prompt enumerates hypothesis statuses
- **WHEN** 构造评估器提示词
- **THEN** MUST 列出 pending、investigating、supported、contradicted、blocked、unresolved 六个合法取值，使模型无需猜测枚举；模型给出其它取值时 MUST 作为结构校验失败并按既有修正与收尾规则处理。
