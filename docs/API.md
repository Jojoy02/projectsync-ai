# ProjectSync API

管理接口使用 `X-Admin-Token: <API_ADMIN_TOKEN>`。`/health` 与飞书事件回调除外。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 检查服务、Dify、飞书和写回配置 |
| POST | `/webhooks/feishu/events` | 飞书事件回调 |
| GET | `/api/users` | 列出已通过机器人使用过的租户/用户标识，供管理员配置映射 |
| GET | `/api/scopes?tenant_id=...&user_id=...` | 查看已授权的文件夹资料范围 |
| GET | `/api/projects/ownership?tenant_id=...&user_id=...` | 查看当前用户范围内的项目归属元数据 |
| GET | `/api/docs/blocks?url=...` | 查看指定文档的文本块 ID，供配置写回目标使用 |
| POST | `/api/targets` | 设置某个用户的日报/周报目标文档与段落块 |
| POST | `/api/ingest` | 管理员/集成方写入一条事实 |
| GET | `/api/facts?tenant_id=...&user_id=...` | 查询某个用户的事实记录 |
| POST | `/api/users/settings` | 配置用户时区、日报/周报时间和日历 ID |
| POST | `/api/sync/sources` | 立即同步已登记文档来源 |
| POST | `/api/sync/calendar` | 立即同步已配置日历 |
| POST | `/api/scheduler/run` | 手动运行一次定时任务检查 |
| POST | `/api/test/dify` | 测试 Dify Chatflow API |

## 设置目标映射示例

```json
{
  "tenant_id": "tenant-key-from-feishu-event",
  "user_id": "open-id-from-feishu-event",
  "report_type": "weekly",
  "document_url": "https://example.feishu.cn/docx/document-token",
  "block_id": "block-id-from-docs-block-list"
}
```

## 写入事实示例

```json
{
  "tenant_id": "tenant-key-from-feishu-event",
  "user_id": "open-id-from-feishu-event",
  "content": "完成接口联调，等待业务验收",
  "occurred_at": "2026-10-29",
  "business": "交易渠道",
  "project": "渠道接入",
  "contribution": "completed",
  "source_url": "https://example.feishu.cn/docx/document-token",
  "source_excerpt": "联调记录：接口联调完成，等待业务验收"
}
```
