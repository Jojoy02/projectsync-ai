# Dify Chatflow 配置

## 1. 创建应用

1. 打开你的 Dify 工作区，创建 **Chatflow / Advanced Chat** 应用（不要创建只有一次性输出的 Workflow，因为飞书桥接使用 `/v1/chat-messages`）。
2. 首选导入 `dify/projectsync_chatflow.yml`。
3. 导入后打开 LLM 节点，选择你工作区已配置的模型供应商和模型。模板默认示例为 `gpt-4o-mini`；若没有该模型，请换成工作区实际可用的模型。
4. 检查系统提示词。完整版本在 `dify/system_prompt.md`，可直接复制到 LLM 节点的 System Prompt。
5. 发布应用。
6. 在应用的 API Access 页面创建/复制 App API Key。
7. 将 Dify API 根地址和 Key 写入服务端 `.env`：

```dotenv
DIFY_BASE_URL=https://api.dify.ai
DIFY_APP_API_KEY=app-替换为你的key
```

如果使用自部署 Dify，把 `DIFY_BASE_URL` 改成该实例的 API 根地址。不要把 App API Key 放进前端、Skill 公共文件或 GitHub 仓库。

## 2. 这个 Chatflow 做什么

后端会把任务类型、当前用户标识、相关事实、待修改草稿或文档文本作为 JSON 放进 `query`，Chatflow 按 `task` 输出 JSON。后端负责保存事实、草稿状态、确认、权限和写回保护；模型本身不直接改正式文档。

支持任务：

- `classify`：识别用户是记录工作、提问、生成报告还是修改草稿。
- `extract_facts`：从文档中抽取工作事实和证据。
- `generate_daily` / `generate_weekly`：生成日报或周报草稿。
- `edit_draft`：按自然语言局部修改当前草稿。
- `query`：基于已有事实回答项目与待办问题。

## 3. 测试

服务启动后，设置管理令牌：

```bash
curl -X POST http://127.0.0.1:8080/api/test/dify \
  -H "X-Admin-Token: 你的API_ADMIN_TOKEN"
```

预期返回 `ok: true` 和结构化 JSON。若报 401/403，检查 Dify App API Key；若输出不是 JSON，检查是否使用了 `dify/system_prompt.md` 中的输出契约。

## 4. 导入不兼容时

Dify 不同版本的 DSL 字段和模型供应商标识可能变化。如果导入提示节点或模型配置不兼容：

1. 在 Dify UI 手动创建 Chatflow。
2. 添加一个 LLM 节点，System Prompt 粘贴 `dify/system_prompt.md`。
3. User Prompt 填入 `{{#sys.query#}}`。
4. 将 LLM 输出连接到 Answer 节点，Answer 内容填 `{{#llm.text#}}`（如果节点 ID 不同，请选择实际 LLM 节点的 `text` 输出变量）。
5. 选择模型、发布应用并重新获取 API Key。

不需要在 Dify 中配置飞书凭证；飞书凭证只放在 ProjectSync 后端的 `.env`。
