# 飞书自建应用机器人配置

本项目使用**飞书开放平台的自建应用机器人**，而不是只能推送、不能接收用户消息的群自定义机器人。机器人事件由 ProjectSync 后端接收，后端调用 Dify，再以应用身份向用户发送回复。

## 1. 创建应用

1. 在飞书开放平台创建企业自建应用。
2. 开启机器人能力。
3. 在事件订阅中配置请求地址：

   `https://你的公网域名/webhooks/feishu/events`

4. 配置事件订阅：`im.message.receive_v1`（接收消息 v2.0）。MVP 建议先从用户与机器人单聊开始，不要一开始就申请读取群内全部消息的敏感权限。
5. 将飞书事件订阅页面的 Verification Token 填入 `.env` 的 `FEISHU_VERIFICATION_TOKEN`。
6. 若启用事件加密，填写 `FEISHU_ENCRYPT_KEY`；否则在事件订阅设置中使用未加密回调，并确保公网 HTTPS 和 Verification Token 已配置。
7. 申请并发布应用版本，让机器人在测试用户范围内可用。

## 2. 权限原则

请按你实际启用的接口，在飞书开放平台为应用申请对应权限，并按企业流程审批。至少需要：

- 接收用户发给机器人的单聊消息；
- 以应用身份发送消息；
- 读取新版云文档块；
- 若启用文档写回，申请编辑相应云文档块的权限；
- 若启用日历同步，申请读取日历/日程的权限。

具体权限名称以飞书开放平台中相应 API 的权限页为准，不要为了方便申请读取所有群消息或全租户所有文档的权限。

## 3. 配置服务端

将以下字段填入 `.env`：

```dotenv
FEISHU_API_BASE=https://open.feishu.cn/open-apis
FEISHU_APP_ID=cli_你的AppID
FEISHU_APP_SECRET=你的AppSecret
FEISHU_VERIFICATION_TOKEN=事件订阅的VerificationToken
FEISHU_ENCRYPT_KEY=
PUBLIC_BASE_URL=https://你的公网域名
```

保存后重启服务。调用 `/health` 检查 `feishu_configured` 为 `true`。

## 4. 测试消息收发

在飞书客户端打开机器人单聊，发送：

`帮助`

机器人应返回支持的指令。随后发送：

`记录：完成了接口联调，等待业务验收`

应收到“已记录”回复。当前用户的工作记录按飞书 `tenant_key + open_id` 隔离。

## 5. 添加工作文档

发送：

`添加文档 https://你的租户.feishu.cn/docx/实际文档ID`

应用必须有权读取该文档。若出现无权限错误，在文档的分享/应用权限设置中将应用添加为有权访问的应用，或通过企业认可的授权方式开放读取。

会议纪要可以作为文档链接添加。也可以发送“添加资料范围 https://你的租户.feishu.cn/drive/folder/文件夹Token”，让服务扫描该授权文件夹及其有限层级的子文件夹中的新版云文档。请只授权确实需要的文件夹。知识空间/Wiki 根节点暂未自动发现。日历需要另外配置日历 ID，并确保应用身份对该日历拥有读取权限。日历事件只作为背景信息，不能单独证明任务完成。

## 官方文档

- [机器人概述](https://open.feishu.cn/document/client-docs/bot-v3/bot-overview)
- [接收消息事件](https://open.feishu.cn/document/server-docs/im-v1/message/events/receive)
- [发送消息 API](https://open.feishu.cn/document/server-docs/im-v1/message/create)
- [事件订阅概述](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/event-subscription-guide/event-subscriptions)
- [获取日程列表](https://open.feishu.cn/document/server-docs/calendar-v4/calendar-event/list)
