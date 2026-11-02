## REMOVED Requirements

### Requirement: Chinese MCP management workspace
**Reason**：前端 MCP 管理工作区（视图、store、客户端、路由与侧栏入口）随工作区收敛一并移除，界面层不再提供连接配置、检查与工具发现。
**Migration**：MCP 连接的创建、更新、启停、删除、检查与工具发现接口保留在后端，其他客户端仍可使用；AIOps 与聊天继续按当前用户启用的连接装配工具。
