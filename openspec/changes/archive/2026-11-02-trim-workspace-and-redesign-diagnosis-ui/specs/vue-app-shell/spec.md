## MODIFIED Requirements

### Requirement: Route-based application shell
认证后的应用 SHALL 提供 `/aiops` 与 `/mcp` 工作区，并在桌面侧栏与移动导航中提供一致入口；根路径、未知路径与登录后落地页 MUST 指向智能诊断工作区。

#### Scenario: 用户打开 MCP 管理
- **WHEN** 已认证用户访问 `/mcp`
- **THEN** 应用 MUST 在共享工作区框架中显示 MCP 连接管理页面。

#### Scenario: 用户打开工作区根路径
- **WHEN** 已认证用户访问 `/` 或任意未定义路径
- **THEN** 应用 MUST 将其送到 `/aiops`，MUST NOT 暴露已移除的工作区路由。

### Requirement: Routed workspaces fill the desktop application surface
工作区 SHALL 将全局 header 以下、左侧栏右侧的全部可用桌面空间交给当前路由视图，不得使用居中最大宽度或通用外层留白缩小业务界面。

#### Scenario: User opens a primary workspace
- **WHEN** user 打开智能诊断或 MCP 连接任一桌面 Web 路由
- **THEN** 对应根视图 MUST 紧贴路由内容区边界并占满可用宽度和高度，MUST NOT 暴露外围 canvas 留白

#### Scenario: Workspace content is longer than its surface
- **WHEN** 当前业务视图内容超过可用高度
- **THEN** 业务视图 MUST 在自身定义的区域内滚动，MUST NOT 通过全局内容 padding 或文档滚动制造额外留白

## REMOVED Requirements

### Requirement: Chat sessions live in the workspace sidebar
**Reason**：对话板块整体移出工作区，会话侧栏不再存在。
**Migration**：会话的创建、选择与删除仍由后端 HTTP 能力提供，其他客户端可继续使用；工作区不再渲染会话列表。
