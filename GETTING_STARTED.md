# ProjectSync AI — Getting Started

项目包含两个运行版本：

- `skills/projectsync/SKILL.md`：Codex、Claude Code 等 Agent Skill。
- `dify/projectsync_chatflow.yml` + `projectsync/`：Dify Chatflow + 飞书机器人后端。

## 最短落地路径

1. 安装依赖并复制配置：`pip install -r requirements.txt`，复制 `.env.example` 为 `.env`。
2. 先配置 `DIFY_BASE_URL`、`DIFY_APP_API_KEY`，在 Dify 导入 `dify/projectsync_chatflow.yml`、选择模型并发布。
3. 配置飞书自建应用凭证与事件订阅，回调地址使用 `https://你的域名/webhooks/feishu/events`。
4. 启动：`uvicorn projectsync.main:app --host 0.0.0.0 --port 8080`。
5. 在飞书机器人私聊发送 `帮助`、`记录：完成接口联调，等待验收`，验证基本流程。
6. 发送 `添加资料范围 <飞书文件夹链接>` 或 `添加文档 <飞书docx链接>`，测试授权范围发现与文档提取。
7. 先保持 `WRITEBACK_ENABLED=false`。用 `/api/docs/blocks` 查找测试文档的文本块 ID，再用 `/api/targets` 配置日报/周报目标。确认只读链路正确后，才在测试文档上开启写回。

## 两种版本的区别

| | Agent Skill | Dify + 飞书机器人 |
|---|---|---|
| 入口 | Codex / Claude Code 等宿主 Agent | 飞书机器人会话 |
| 文档权限 | 宿主当前连接的 MCP/API 工具 | 飞书应用获得的文档/日历权限 |
| 记忆 | 本地 CLI 数据库或宿主已有记忆 | 后端 SQLite，按租户 + 用户隔离 |
| 定时日报/周报 | 取决于宿主是否提供调度 | 后端 APScheduler |
| 正式写回 | 由宿主授权编辑工具执行 | 飞书 API，需目标块映射并开启 `WRITEBACK_ENABLED` |

**重要：** 本包不包含你的飞书 App Secret、Dify API Key 或真实文档权限。需要在自己的环境中配置。写回默认关闭，不会在第一次启动时修改正式文档。
