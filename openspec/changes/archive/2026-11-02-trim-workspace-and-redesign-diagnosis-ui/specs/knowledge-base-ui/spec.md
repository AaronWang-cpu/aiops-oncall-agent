## REMOVED Requirements

### Requirement: Authenticated knowledge document workspace
**Reason**：知识库板块与其文档工作区整体移出前端，工作区只保留告警处理。
**Migration**：知识库与文档的 HTTP 能力保留；前端不再提供 `/knowledge` 这一工作区。

### Requirement: Policy-aware document upload
**Reason**：上传入口随知识库界面移除。
**Migration**：上传策略与接口保留在后端与共享合同中。

### Requirement: Document index lifecycle visibility
**Reason**：文档索引生命周期只在知识库界面呈现。
**Migration**：索引任务与后台任务能力保留；AIOps 案例保存仍可触发索引。

### Requirement: Document inspection and deletion
**Reason**：文档元数据展开与删除入口随知识库界面移除。
**Migration**：相关端点保留，其他客户端仍可使用。

### Requirement: Responsive knowledge operations
**Reason**：不再存在知识库界面需要响应式处理。
**Migration**：无。

### Requirement: Chunking selection and preview UI
**Reason**：切分策略选择与预览属于上传流程，随知识库界面移除。
**Migration**：切分策略仍由后端决定并持久化。

### Requirement: Scrollable knowledge document workspace
**Reason**：文档列表滚动行为随知识库界面移除。
**Migration**：诊断工作区各列保留独立滚动。
