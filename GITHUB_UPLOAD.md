# GitHub 上传说明

建议仓库名：`projectsync-ai`。

1. 在 GitHub 新建一个名为 `projectsync-ai` 的仓库。
2. 将本目录内的文件与文件夹上传到仓库根目录。
3. 默认分支使用 `main`。
4. 推送后，在仓库 **Settings → Pages** 中选择 **GitHub Actions**。
5. `.github/workflows/pages.yml` 会发布 `site/index.html`。介绍页和交互 Demo 可以通过 GitHub Pages 访问。
6. Python 后端需要单独部署；GitHub Pages 只托管静态展示页，不运行 FastAPI、定时任务或飞书回调服务。

上传前再次确认没有加入 `.env`、数据库文件、真实工作记录或应用凭证。


界面说明：`demo/ProjectSyncAI-Intro-and-Interactive-Demo.html` 为本次更新后的界面与交互 Demo；根目录 `index.html` 和 `site/index.html` 是同内容入口，不要用其他原型页面覆盖。
