# 安装 ProjectSync Agent Skill

Skill 使用宿主 Agent 已经授权的文档/MCP/API 工具。它不会因为安装了 Skill 就自动获得飞书权限，也不会凭空获得后台定时执行能力。

## 1. 安装核心包与 CLI

在项目根目录：

```bash
pip install -e .
python skills/projectsync/scripts/projectsync_cli.py init
```

默认私有数据库路径：`~/.projectsync/projectsync.sqlite3`。不要将此文件提交到 Git。

## 2. 放到宿主 Agent 的 Skill 目录

把 `skills/projectsync/` 整个目录复制到对应宿主支持的 Skill 路径。例如：

- Codex：项目级 `.agents/skills/projectsync/` 或用户级 Skill 目录；
- Claude Code：项目级 `.claude/skills/projectsync/` 或用户级 Skill 目录；
- 其他支持 `SKILL.md` 的 Agent：按该平台的 Skill 安装规范放置。

如果直接在当前仓库里使用，无需复制。

## 3. 让宿主读取工作资料

在宿主 Agent 中连接你有权使用的飞书文档 MCP、文档搜索工具或其他企业资料工具。Skill 会指导 Agent 读取计划、进展、会议纪要和日历上下文，先识别个人事实，再按业务与项目归类。

如果宿主没有文档工具，用户可以主动粘贴内容或提供可访问链接；Skill 不会声称已读取未访问的资料。

## 4. 本地记录示例

```bash
python skills/projectsync/scripts/projectsync_cli.py add-fact \
  --content "完成接口联调，等待业务验收" \
  --business "交易渠道" --project "渠道接入" \
  --contribution completed --date 2026-10-29

python skills/projectsync/scripts/projectsync_cli.py list-facts --since 2026-10-27
python skills/projectsync/scripts/projectsync_cli.py update-fact --id FACT_ID --business "交易渠道" --project "渠道接入"
python skills/projectsync/scripts/projectsync_cli.py set-project-ownership --project "渠道接入" --business "交易渠道" --owner-name "当前用户" --owner-user-id "local-user" --role owner
```

## 5. 写回边界

CLI 的 `confirm-draft` 只记录本地确认状态，不会写在线文档。宿主 Agent 只有在用户明确确认后，才可通过已授权的文档编辑工具写回；写回前应重新读取目标文档并检查冲突。若宿主不支持在线编辑，只展示已确认文本，不要声称已更新。
