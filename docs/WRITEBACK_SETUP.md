# 配置在线文档安全写回

写回默认关闭。先验证消息、事实抽取和草稿流程，再用专门的测试文档验证写回。

## 1. 准备目标段落

MVP 写回只更新一个明确映射的**普通段落块**。建议在测试文档中为当前用户的日报或周报条目准备一个独立段落块；不要映射到标题、表格、整份文档或他人条目。

飞书文档 URL 需要是新版云文档链接，路径形如 `/docx/<document_id>`。

## 2. 找到 block ID

服务运行后执行：

```bash
curl -G "http://127.0.0.1:8080/api/docs/blocks" \
  -H "X-Admin-Token: 你的API_ADMIN_TOKEN" \
  --data-urlencode "url=https://你的租户.feishu.cn/docx/实际文档ID"
```

响应会列出包含文本的块 ID 和内容。找到专门为当前用户准备的普通段落块，记下 `block_id`。

## 3. 建立日报/周报目标映射

```bash
curl -X POST "http://127.0.0.1:8080/api/targets" \
  -H "X-Admin-Token: 你的API_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id":"飞书事件中的tenant_key",
    "user_id":"该用户在本应用中的open_id",
    "report_type":"daily",
    "document_url":"https://你的租户.feishu.cn/docx/实际文档ID",
    "block_id":"你选定的段落块ID"
  }'
```

`report_type` 使用 `daily` 或 `weekly`。周报映射同样调用一次，目标块可以属于同一文档，但必须是不同且明确的段落块。生产中不要把 `tenant_id` / `user_id` 填成示例值，应从飞书事件或服务数据中核实。

## 4. 先只确认，不写入

保持 `.env`：

```dotenv
WRITEBACK_ENABLED=false
```

生成日报，修改草稿，再回复“确认日报”。预期结果是记录确认状态，但正式文档不变。

## 5. 启用写回

只有在测试文档验证成功后，才将 `WRITEBACK_ENABLED=true` 并重启服务。确认时服务会：

1. 检查该草稿确实属于当前 `tenant_id + user_id`；
2. 读取目标段落当前文本；
3. 与生成草稿时的文本快照比较；
4. 如目标内容变化则停止写回；
5. 仅尝试更新映射的普通段落块；
6. 根据 API 结果记录成功或失败。

如果 API 超时、块类型不支持、权限不足或版本发生变化，服务不会报告“已发布”。

> 注意：不同租户的文档权限与 API 版本可能不同。首次启用真实写回前，必须在该租户的测试文档上验证 `PATCH /docx/v1/documents/{document_id}/blocks/{block_id}` 的实际请求与权限。MVP 不会自动推断共享周报中复杂的成员区段；复杂表格/多段条目定位器属于后续实现。
