## REMOVED Requirements

### Requirement: Persisted conversation workspace
**Reason**：工作区只保留告警处理，对话板块与其会话入口整体移除。
**Migration**：会话创建、列表、选择与删除仍由后端 HTTP 能力提供；前端不再实现该工作区。

### Requirement: Streaming chat interaction
**Reason**：对话界面移除后，前端不再消费聊天流式回答。
**Migration**：聊天 SSE 能力保留在后端；AIOps 流式订阅不受影响。

### Requirement: Answer context presentation
**Reason**：对话回答、引用与工具上下文的展示随对话界面移除。
**Migration**：共享消息与 SSE 合同保持不变，其他客户端仍可使用。

### Requirement: Responsive chat feedback states
**Reason**：不再存在对话工作区需要响应式反馈状态。
**Migration**：通用加载、空状态、错误与状态组件保留，供诊断与连接工作区继续使用。

### Requirement: Chat assembly controls
**Reason**：系统提示词与 Skill 配置侧栏属于对话能力，随对话界面移除。
**Migration**：装配配置的后端接口保留；AIOps 诊断使用固定提示与项目知识，不依赖该配置。

### Requirement: Collapsible assistant execution context
**Reason**：助手消息与其工具/推理折叠区随对话界面移除。
**Migration**：诊断执行链改为在过程列展示持久化步骤与工具调用，并关联证据。

### Requirement: Compact keyboard-first chat composer
**Reason**：对话输入框随对话界面移除。
**Migration**：诊断命令带保留键盘提交与可选告警上下文校验。

### Requirement: Content-sized user message bubbles
**Reason**：消息气泡样式随对话界面移除。
**Migration**：无。

### Requirement: Conversation-first chat workspace layout
**Reason**：对话优先布局随对话界面移除。
**Migration**：工作区主表面现在由诊断工作区占用。

### Requirement: Neutral chat focus treatment
**Reason**：该焦点样式只服务于聊天输入界面。
**Migration**：诊断输入沿用工作区通用焦点样式。

### Requirement: Empty chat transcript remains blank
**Reason**：空对话记录区随对话界面移除。
**Migration**：诊断的历史、证据与账本视图各自提供明确空状态。

### Requirement: Session memory controls beside composer
**Reason**：会话记忆控件随对话界面移除。
**Migration**：后端会话记忆能力保留，其他客户端可继续使用。

### Requirement: Composer context limit feedback
**Reason**：上下文硬上限提示绑定在聊天输入区。
**Migration**：后端限制逻辑保留；诊断链路由自身预算机制约束。

### Requirement: Reranked citation presentation
**Reason**：引用精排列表随对话界面移除。
**Migration**：检索与重排能力保留在后端与共享合同中。

### Requirement: Current-turn citation isolation
**Reason**：本轮引用隔离只对对话流有意义。
**Migration**：无。

### Requirement: Character-by-character answer rendering
**Reason**：逐字渲染随对话界面移除。
**Migration**：诊断时间线按事件增量展示，不做打字机动画。

### Requirement: Perceptible model typewriter pacing
**Reason**：打字机节奏只服务于聊天回答。
**Migration**：无。

### Requirement: Chat answer and citation feedback
**Reason**：回答与引用反馈入口随对话界面移除。
**Migration**：诊断步骤与报告反馈入口保留。
