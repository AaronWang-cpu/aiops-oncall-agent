## MODIFIED Requirements

### Requirement: Chinese AI workspace visual language
经过身份验证的前端 SHALL 会渲染一个以中文语言显示的AI工作区，包含一个持久化的桌面导航栏、一个专注的主要工作表面、语义状态颜色以及响应式的移动导航模式。面向用户的文本 MUST 应为中文，除非是必要的技术术语、模型名称、MCP、SSE 以及由工具原样返回的数据；工作台品牌与页头 MUST 以中文呈现为「AIOps 诊断台」。

#### Scenario: Authenticated user enters a workspace
- **WHEN** 已认证的 user 在桌面视口上打开智能诊断工作区
- **THEN** 前端 MUST 以统一的视觉语言展示稳定的导航栏、当前工作区上下文、账户控制以及不重叠的主要工作区域。

#### Scenario: User opens a narrow viewport
- **WHEN** 已认证的 user 在窄视口下打开工作区
- **THEN** 主导航、路由内容、标题、操作和长中文标签 MUST 在不出现水平页面溢出的情况下仍可访问。
