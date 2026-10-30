# ProjectSync AI

**工作信息跟踪与总结 Agent。** 从授权的工作文档、会议记录、日历上下文和用户主动记录中识别个人实际工作，关联业务与项目，准备日报/周报草稿，并在用户确认后安全更新指定的在线文档。

> 当前版本是可自行部署的 MVP 源码，不是已经连接企业租户的托管服务。真实接入需要配置自己的 Dify、飞书应用凭证、访问权限与 HTTPS 回调地址。默认关闭正式文档写回。

## 预览

产品介绍与可交互 Demo 使用原版文件 [`demo/ProjectSyncAI-Intro-and-Interactive-Demo.html`](./demo/ProjectSyncAI-Intro-and-Interactive-Demo.html)，界面与交互逻辑保持原样。仓库根目录的 [`index.html`](./index.html) 和 `site/index.html` 是该文件的同内容发布入口。GitHub Pages 工作流只发布 `site/` 中的静态页面，不会把后端源码作为网站文件部署。

## 两种运行方式

- **Agent Skill**：位于 `skills/projectsync/SKILL.md`，面向 Codex、Claude Code 等支持 Skill 的宿主 Agent。文档读写权限取决于宿主连接的工具。
- **Dify + 飞书机器人**：飞书自建应用机器人接收消息，后端调用 Dify Chatflow 处理工作事实、总结和自然语言修改，并通过飞书 API 读取授权文档与执行受控写回。

两种入口共用工作事实、项目关联、草稿和安全规则。

## 核心能力

- 按租户与用户隔离工作事实、来源、草稿和目标文档映射。
- 从工作记录中识别个人贡献，并保留来源和证据。
- 业务与项目双主线跟踪；同一条事实可关联两者，但底层只记录一次。
- 自动关联高置信度资料，存疑内容保留待核验状态。
- 生成日报和周报草稿，支持自然语言修改与分别确认。
- 写回默认关闭；正式写回前进行目标映射、快照比对和冲突检查。
- 提供 Dify Chatflow 模板、部署说明、示例数据和自动化测试。

## 快速启动

要求 Python 3.11 或更新版本。

```bash
python -m venv .venv

# Windows PowerShell
.venv\\Scripts\\Activate.ps1

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

复制 `.env.example` 为 `.env`，至少设置 `API_ADMIN_TOKEN`。接入 Dify 与飞书时，再按下列文档配置对应凭证。

```bash
# Windows PowerShell
Copy-Item .env.example .env

# macOS / Linux
cp .env.example .env
```

启动服务：

```bash
uvicorn projectsync.main:app --reload --port 8080
```

健康检查：`http://127.0.0.1:8080/health`

运行测试：

```bash
pytest -q
```

## 配置指南

- [完整启动步骤](./GETTING_STARTED.md)
- [Dify Chatflow 配置](./docs/DIFY_SETUP.md)
- [飞书机器人与权限配置](./docs/FEISHU_SETUP.md)
- [安全与数据保护](./docs/SECURITY.md)
- [在线文档写回配置](./docs/WRITEBACK_SETUP.md)
- [Agent Skill 本地使用](./docs/LOCAL_SKILL.md)
- [API 说明](./docs/API.md)
- [当前实现状态与限制](./docs/IMPLEMENTATION_STATUS.md)

## 运行架构

```text
飞书机器人
    │
    ▼
ProjectSync API (FastAPI) ─── SQLite：事实、来源、草稿与审计
    │
    ├── Dify Chatflow：事实抽取、归类、总结与自然语言修改
    └── 飞书 OpenAPI：消息、云文档与可选日历

Agent Skill
    └── 宿主已授权的文档工具 + 本地事实与草稿存储
```

## 安全说明

- 不要提交 `.env`、API Key、应用 Secret、数据库、真实工作记录或客户资料。
- `.env.example` 只包含占位值。
- `WRITEBACK_ENABLED=false` 为默认值。先在测试文档验证读取、目标段落映射和冲突处理，再考虑开启写回。
- 共享文档只应更新已明确映射且属于当前用户权限范围的内容。

## 当前边界

- 目前主要适配飞书新版云文档；完整知识空间/Wiki 自动发现尚未实现。
- 会议纪要通过已授权文档接入；日历需要单独配置可访问的日历 ID。
- 写回 MVP 针对显式映射的普通文本块，复杂表格和多人混排模板需要后续扩展。
- Dify Chatflow 模板需要在目标 Dify 工作区导入、配置模型并发布后验证。
- 腾讯文档、语雀、Google Docs 等连接器不在当前 MVP 范围内。

## 仓库结构

```text
projectsync-ai/
├── index.html                 # 本地预览入口：原版介绍页 + 交互 Demo
├── demo/ProjectSyncAI-Intro-and-Interactive-Demo.html  # 原始界面与 Demo 文件
├── site/index.html            # GitHub Pages 发布入口
├── projectsync/               # FastAPI、存储、业务逻辑与飞书/Dify 客户端
├── skills/projectsync/        # Agent Skill 与本地 CLI
├── dify/                      # Chatflow 模板与系统提示词
├── docs/                      # 部署、权限、安全与写回说明
├── tests/                     # 自动化测试
├── examples/                  # 示例工作事实和会议记录
├── .env.example               # 环境变量模板（无真实密钥）
└── GETTING_STARTED.md         # 快速启动
```

## 状态

MVP 源码已整理，自动化测试与集成配置仍需在目标 Dify 工作区、飞书租户和测试文档中验证。该项目不会在未配置凭证的情况下自动连接或修改真实企业资料。
