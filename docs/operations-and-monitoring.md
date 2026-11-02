# 配置与运维

应用只读取本地 `config/project.json` 和可选的 `config/user.project.json`，不读取本机环境变量。两个文件都被 Git 忽略；仓库只保留不含真实凭据的模板。不要为本项目创建 `.env` 文件，也不要提交本地配置。

首次使用时，在仓库根目录执行：

```bash
cp config/project.template.json config/project.json
cp config/user.project.template.json config/user.project.json
```

## 项目交付后的个人配置

在本地 `config/user.project.json` 中填写使用者自己的模型密钥、CLS 凭据和 CLS 日志目标。其他运行参数可在本地 `config/project.json` 中调整：

| 配置字段 | 替换为 |
| --- | --- |
| `llm.apiKey` | 使用者自己的聊天模型密钥（默认供应商 DeepSeek） |
| `llm.chatModel` | 使用者自己的聊天模型名，并在 `llm.modelCapabilities` 中补同名能力档案 |
| `llm.embeddingApiKey` | 嵌入与重排使用的百炼密钥（缺省复用 `llm.apiKey`） |
| `llm.rerankApiKey` | 重排独立密钥，仅在重排与嵌入不同账号时填写 |
| `clsMcpServer.secretId` | 使用者自己的 CLS 凭据 ID |
| `clsMcpServer.secretKey` | 使用者自己的 CLS 凭据密钥 |
| `clsLogUpload.region` | 使用者自己的 CLS 地域 |
| `clsLogUpload.logsetId` | 使用者自己的 CLS 日志集 ID |
| `clsLogUpload.topicId` | 使用者自己的 CLS 主题 ID |

聊天模型与嵌入、重排可以分属不同供应商：`llm.baseUrl`/`llm.apiKey` 决定聊天端点，`llm.embeddingBaseUrl`/`llm.embeddingApiKey` 决定嵌入端点，重排使用 `llm.rerankUrl`/`llm.rerankApiKey`。跟踪的默认值把聊天放在 DeepSeek，把嵌入与重排留在阿里云百炼，因此这两个平台的密钥都需要填写；`llm.embeddingBaseUrl` 已在基础配置中指向百炼，通常无需改动。

模板中的凭据字段必须保持为空。即使仓库是私有仓库，也不要提交真实密钥；已暴露的密钥应在对应云平台立即轮换。

## 真实日志与本地告警样例

真实 CLS 日志上传和本地 active-alert 演示属于显式运维流程，不是常规应用启动的一部分。请遵循[真实 CLS 日志与告警教程](tutorials/real-log-and-alert.md)，分别执行其中的日志上传脚本和本地告警命令。
