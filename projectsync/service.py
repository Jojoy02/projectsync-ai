from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .config import settings
from .core import (
    facts_context, fallback_query, local_draft, looks_like_add_doc, looks_like_add_scope,
    looks_like_confirm, looks_like_daily, looks_like_edit, looks_like_help,
    looks_like_record, looks_like_weekly, parse_docx_url, parse_folder_url, period_for, text_hash, today_in,
)
from .dify_client import DifyClient
from .feishu import FeishuClient, block_text
from .store import Store

logger = logging.getLogger("projectsync")

HELP_TEXT = """我可以帮你持续整理个人工作和项目进展。

直接发送：
- 记录：完成了什么
- 添加文档 https://.../docx/...
- 添加资料范围 https://.../drive/folder/...
- 生成日报 / 生成周报
- 确认日报 / 确认周报
- 我最近跟进哪些项目
- 设置日报时间 18:00
- 设置周报时间 周五 18:00
- 设置日历 <日历ID>
- 最近记录
- 调整归属 <记录ID> | 业务=业务名 | 项目=项目名
- 设置项目归属 项目名 | 业务=业务名 | 负责人=我 | 角色=负责人

日报和周报会先生成草稿。只有你明确确认后，才会尝试写入已配置的在线文档。"""


class ProjectSyncService:
    def __init__(self, store: Store | None = None, dify: DifyClient | None = None, feishu: FeishuClient | None = None):
        self.store = store or Store()
        self.dify = dify or DifyClient()
        self.feishu = feishu or FeishuClient()

    async def handle_message(self, tenant_id: str, user_id: str, text: str) -> str:
        user = self.store.ensure_user(
            tenant_id, user_id, timezone=settings.feishu_timezone,
            daily_time=settings.default_daily_time, weekly_day=settings.default_weekly_day,
            weekly_time=settings.default_weekly_time, calendar_id=settings.feishu_calendar_id,
        )
        text = (text or "").strip()
        if not text:
            return "请发送工作进展、文档链接，或输入“帮助”查看可用操作。"
        if looks_like_help(text):
            return HELP_TEXT

        ownership_reply = self._handle_ownership_commands(tenant_id, user_id, text)
        if ownership_reply:
            return ownership_reply

        setting_reply = self._handle_settings(tenant_id, user_id, text)
        if setting_reply:
            return setting_reply

        scope_url = looks_like_add_scope(text)
        if scope_url:
            try:
                folder_token = parse_folder_url(scope_url)
                scope = self.store.add_source_scope(tenant_id, user_id, scope_url, folder_token)
                discovered = await self.discover_scope(scope)
                if self.dify.configured:
                    created_facts = 0
                    for source in discovered:
                        try:
                            count, _changed = await self.sync_source(source)
                            created_facts += count
                        except Exception:
                            logger.exception("new scope document sync failed")
                    return f"已关联资料范围，发现 {len(discovered)} 篇新版云文档，新增 {created_facts} 条工作事实。后续会定期检查文件夹变化。"
                return f"已关联资料范围，发现 {len(discovered)} 篇新版云文档。配置 Dify Chatflow 后即可自动提取事实；目前不会把文档原文直接当作个人成果。"
            except Exception as exc:
                logger.exception("scope discovery failed")
                return f"资料范围已尝试登记，但读取失败：{self._short_error(exc)}。请确认应用有权访问该文件夹。"

        doc_url = looks_like_add_doc(text)
        if doc_url:
            try:
                doc_id = parse_docx_url(doc_url)
                source = self.store.add_source(tenant_id, user_id, doc_url, doc_id)
            except ValueError as exc:
                return str(exc)
            if not self.dify.configured:
                return f"文档已登记（{doc_id}）。要自动提取其中的工作事实，请先配置 Dify Chatflow API Key；目前不会把整篇文档直接当作个人成果。"
            try:
                count, changed = await self.sync_source(source)
                return f"已关联文档，{'发现并记录 ' + str(count) + ' 条工作事实' if changed else '未发现新的工作事实'}。后续同步会增量检查，文档中的团队成果不会自动归为你的个人成果。"
            except Exception as exc:
                logger.exception("sync source failed")
                return f"文档已登记，但读取或解析失败：{self._short_error(exc)}。请确认应用已被添加到该文档，并拥有相应读取权限。"

        fact_text = looks_like_record(text)
        if fact_text:
            return await self._record_from_message(tenant_id, user_id, fact_text)

        confirmed, kind = looks_like_confirm(text)
        if confirmed:
            return await self.confirm_draft(tenant_id, user_id, kind)

        if looks_like_daily(text):
            return await self.generate_draft(tenant_id, user_id, "daily", force="重新生成" in text)
        if looks_like_weekly(text):
            return await self.generate_draft(tenant_id, user_id, "weekly", force="重新生成" in text)

        pending_list = self.store.list_drafts(tenant_id, user_id, status="pending_confirmation", limit=10)
        pending_kinds = {d["kind"] for d in pending_list}
        pending = self.store.latest_pending_draft(tenant_id, user_id)
        if looks_like_edit(text) and pending_list:
            requested_kind = "daily" if "日报" in text or "日总结" in text else ("weekly" if "周报" in text or "周总结" in text else None)
            if requested_kind:
                pending = self.store.latest_pending_draft(tenant_id, user_id, requested_kind)
                if not pending:
                    return f"当前没有待修改的{'日报' if requested_kind == 'daily' else '周报'}草稿。"
            elif len(pending_kinds) > 1:
                return "你有日报和周报两份待确认草稿，请说明要修改哪一份，例如“修改日报：……”。"
            if pending:
                return await self.edit_draft(tenant_id, user_id, pending, text)

        # Use Dify to classify free-form work updates, project questions, and edits.
        facts = self.store.list_facts(tenant_id, user_id, limit=50)
        pending = self.store.latest_pending_draft(tenant_id, user_id)
        if self.dify.configured:
            try:
                result = await self.dify.execute(
                    "classify", tenant_id=tenant_id, user_id=user_id, user_message=text,
                    facts=facts_context(facts), current_draft=pending["content"] if pending else "",
                    extra={"pending_draft_kind": pending["kind"] if pending else "", "project_ownership": self.store.list_project_ownership(tenant_id, user_id)},
                )
                if result:
                    intent = result.get("intent", "other")
                    if intent == "record_fact":
                        fact = result.get("fact") or {}
                        content = fact.get("content") or text
                        saved, created = self.store.add_fact(
                            tenant_id, user_id, content, occurred_at=fact.get("occurred_at") or None,
                            business=fact.get("business", ""), project=fact.get("project", ""),
                            contribution=fact.get("contribution", "completed"), confidence=fact.get("confidence", 0.7),
                            source_excerpt=fact.get("source_excerpt", ""),
                        )
                        return ("已记录这条工作进展。" if created else "这条进展已存在，未重复记录。") + self._fact_suffix(saved)
                    if intent in {"generate_daily", "generate_weekly"}:
                        return await self.generate_draft(tenant_id, user_id, "daily" if intent == "generate_daily" else "weekly")
                    if intent == "edit_draft" and pending:
                        requested_kind = "daily" if "日报" in text or "日总结" in text else ("weekly" if "周报" in text or "周总结" in text else None)
                        if len(pending_kinds) > 1 and not requested_kind:
                            return "你有日报和周报两份待确认草稿，请说明要修改哪一份，例如“修改日报：……”。"
                        if requested_kind:
                            pending = self.store.latest_pending_draft(tenant_id, user_id, requested_kind)
                            if not pending:
                                return f"当前没有待修改的{'日报' if requested_kind == 'daily' else '周报'}草稿。"
                        return await self.edit_draft(tenant_id, user_id, pending, text, model_result=result)
                    if intent == "query":
                        return str(result.get("reply") or fallback_query(text, facts))
                    if intent == "help":
                        return HELP_TEXT
                    if result.get("reply"):
                        return str(result["reply"])
            except Exception as exc:
                logger.exception("Dify classify failed; falling back")
                # A Dify outage must not cause a false confirmation or a writeback.
                if self._looks_like_question(text):
                    return fallback_query(text, facts) + "\n\n（AI 服务暂不可用，以上仅基于已记录事实整理。）"

        if self._looks_like_question(text):
            if self.dify.configured:
                try:
                    result = await self.dify.execute("query", tenant_id=tenant_id, user_id=user_id, user_message=text, facts=facts_context(facts))
                    if result and result.get("reply"):
                        return str(result["reply"])
                except Exception:
                    logger.exception("Dify query failed")
            return fallback_query(text, facts)
        return await self._record_from_message(tenant_id, user_id, text)

    @staticmethod
    def _looks_like_question(text: str) -> bool:
        return bool(re.search(r"[？?]|(哪些|什么|如何|怎么|最近|目前|进展|状态|项目|待办|总结一下|帮我查)", text))

    @staticmethod
    def _short_error(exc: Exception) -> str:
        message = str(exc).replace("\n", " ")
        return message[:220] or exc.__class__.__name__

    @staticmethod
    def _fact_suffix(fact: dict[str, Any]) -> str:
        tags = [x for x in [fact.get("business"), fact.get("project")] if x]
        return "\n归类：" + " / ".join(tags) if tags else "\n业务或项目归属可在后续整理时补充。"

    def _handle_ownership_commands(self, tenant_id: str, user_id: str, text: str) -> str | None:
        if text.strip() in {"最近记录", "查看最近记录", "工作记录列表"}:
            facts = self.store.list_facts(tenant_id, user_id, limit=10)
            if not facts:
                return "目前没有工作记录。发送“记录：……”即可添加。"
            lines = ["最近工作记录（可用 ID 调整业务/项目归属）："]
            for fact in facts[-10:][::-1]:
                scope = " / ".join(x for x in [fact.get("business"), fact.get("project")] if x) or "未分类"
                lines.append(f"- {fact['id'][:8]}｜{fact.get('occurred_at','')}｜{fact.get('content','')}（{scope}）")
            lines.append("调整单条记录：调整归属 <ID> | 业务=业务名 | 项目=项目名")
            return "\n".join(lines)

        match = re.match(r"^调整归属\s+([A-Za-z0-9_-]+)\s*\|\s*(.+)$", text.strip(), re.S)
        if match:
            fact_id, raw_fields = match.group(1), match.group(2)
            fields = self._parse_key_values(raw_fields)
            try:
                fact = self.store.update_fact_classification(
                    tenant_id, user_id, fact_id,
                    business=fields.get("业务") if "业务" in fields else None,
                    project=fields.get("项目") if "项目" in fields else None,
                )
                self.store.audit(tenant_id, user_id, "fact_reclassified", fact_id, {"business": fact.get("business"), "project": fact.get("project")})
                return f"已调整记录 {fact_id[:8]} 的归属。\n业务：{fact.get('business') or '未设置'}\n项目：{fact.get('project') or '未设置'}\n原工作事实与来源记录保持不变。"
            except Exception as exc:
                return f"归属调整失败：{self._short_error(exc)}。可先发送“最近记录”查看当前用户范围内的记录 ID。"

        match = re.match(r"^(?:设置|调整)项目归属\s*([^|]+)\|\s*(.+)$", text.strip(), re.S)
        if match:
            project_name = match.group(1).strip()
            fields = self._parse_key_values(match.group(2))
            role_value = fields.get("角色", "参与者").strip().lower()
            role_map = {"负责人": "owner", "owner": "owner", "参与者": "contributor", "贡献者": "contributor", "成员": "contributor", "关注": "observer", "旁观": "observer", "observer": "observer", "contributor": "contributor"}
            role = role_map.get(role_value, "contributor")
            owner_name = fields.get("负责人", "").strip()
            owner_user_id = ""
            if owner_name in {"我", "本人", "当前用户"}:
                owner_user_id = user_id
                owner_name = "当前用户"
                role = "owner"
            elif owner_name and role == "owner":
                # Do not silently transfer personal records to another identity.
                role = "contributor"
            try:
                row = self.store.upsert_project_ownership(
                    tenant_id, user_id, project_name, business=fields.get("业务", ""),
                    owner_name=owner_name, owner_user_id=owner_user_id, role=role,
                    note=fields.get("说明", ""),
                )
                self.store.audit(tenant_id, user_id, "project_ownership_updated", row["id"], {"project": project_name, "business": row.get("business"), "role": role, "owner_name": owner_name})
                role_label = {"owner": "负责人", "contributor": "参与者", "observer": "关注者"}[role]
                return f"已更新你个人工作范围内的项目归属：\n项目：{project_name}\n业务：{row.get('business') or '未设置'}\n负责人：{row.get('owner_name') or '待确认'}\n你的角色：{role_label}\n这只调整项目关联信息，不会转移或读取其他成员的个人工作记录。"
            except Exception as exc:
                return f"项目归属更新失败：{self._short_error(exc)}"
        return None

    @staticmethod
    def _parse_key_values(raw: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for part in raw.split("|"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            result[key.strip()] = value.strip()
        return result

    def _handle_settings(self, tenant_id: str, user_id: str, text: str) -> str | None:
        m = re.fullmatch(r"设置日报时间\s+(\d{1,2}:\d{2})", text)
        if m:
            if not self._valid_time(m.group(1)):
                return "时间格式应为 24 小时制，例如：设置日报时间 18:00"
            self.store.update_user_settings(tenant_id, user_id, daily_time=self._normal_time(m.group(1)))
            return f"日报准备时间已设为 {self._normal_time(m.group(1))}。"
        m = re.fullmatch(r"设置周报时间\s*(周一|周二|周三|周四|周五|周六|周日)?\s*(\d{1,2}:\d{2})", text)
        if m:
            day_map = {"周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6}
            if not self._valid_time(m.group(2)):
                return "时间格式应为 24 小时制，例如：设置周报时间 周五 18:00"
            fields = {"weekly_time": self._normal_time(m.group(2))}
            if m.group(1): fields["weekly_day"] = day_map[m.group(1)]
            self.store.update_user_settings(tenant_id, user_id, **fields)
            user = self.store.get_user(tenant_id, user_id) or {}
            day_label = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][int(user.get("weekly_day", 4))]
            return f"周报准备时间已设为{day_label} {user.get('weekly_time')}。"
        m = re.fullmatch(r"设置时区\s+([A-Za-z_]+/[A-Za-z_+-]+)", text)
        if m:
            try: ZoneInfo(m.group(1))
            except Exception: return "无法识别该时区，请使用 IANA 时区，例如 Asia/Shanghai。"
            self.store.update_user_settings(tenant_id, user_id, timezone=m.group(1))
            return f"时区已设为 {m.group(1)}。"
        m = re.fullmatch(r"设置日历\s+([A-Za-z0-9_@.:-]+)", text)
        if m:
            self.store.update_user_settings(tenant_id, user_id, calendar_id=m.group(1))
            return "日历 ID 已保存。是否能读取取决于飞书应用对该日历的实际权限。"
        return None

    @staticmethod
    def _valid_time(value: str) -> bool:
        try:
            hour, minute = map(int, value.split(":"))
            return 0 <= hour <= 23 and 0 <= minute <= 59
        except Exception:
            return False

    @staticmethod
    def _normal_time(value: str) -> str:
        hour, minute = map(int, value.split(":"))
        return f"{hour:02d}:{minute:02d}"

    async def _record_from_message(self, tenant_id: str, user_id: str, content: str) -> str:
        facts = self.store.list_facts(tenant_id, user_id, limit=50)
        if self.dify.configured and not looks_like_record(content):
            try:
                result = await self.dify.execute("classify", tenant_id=tenant_id, user_id=user_id, user_message=content, facts=facts_context(facts))
                fact = (result or {}).get("fact") or {}
                content = fact.get("content") or content
                saved, created = self.store.add_fact(
                    tenant_id, user_id, content, occurred_at=fact.get("occurred_at") or None,
                    business=fact.get("business", ""), project=fact.get("project", ""),
                    contribution=fact.get("contribution", "completed"), confidence=fact.get("confidence", 0.7),
                    source_excerpt=fact.get("source_excerpt", ""),
                )
                return ("已记录这条工作进展。" if created else "这条进展已存在，未重复记录。") + self._fact_suffix(saved)
            except Exception:
                logger.exception("Dify fact extraction failed")
        saved, created = self.store.add_fact(tenant_id, user_id, content, confidence=0.6)
        return ("已记录这条工作进展。" if created else "这条进展已存在，未重复记录。") + self._fact_suffix(saved)

    async def generate_draft(self, tenant_id: str, user_id: str, kind: str, *, target_date=None, force: bool = False) -> str:
        existing = self.store.latest_pending_draft(tenant_id, user_id, kind)
        if existing and not force:
            title = "日报" if kind == "daily" else "周报"
            return f"已有一份待确认的{title}草稿（编号 {existing['id']}），为避免覆盖你的人工修改，本次没有重新生成。\n\n{existing['content']}\n\n需要重新读取资料并生成新稿，请发送“重新生成{title}”；确认请回复“确认{title}”。"
        if existing and force:
            self.store.supersede_pending_drafts(tenant_id, user_id, kind)
        user = self.store.get_user(tenant_id, user_id) or self.store.ensure_user(tenant_id, user_id)
        today = target_date or today_in(user.get("timezone") or settings.feishu_timezone)
        start, end = period_for(kind, today)
        facts = self.store.list_facts(tenant_id, user_id, start.isoformat(), end.isoformat(), limit=200)
        if kind == "daily" and not facts:
            # For daily reports, don't fabricate a report if no work facts are available.
            return "目前没有足够的已记录工作事实，暂不生成日报。你可以发送“记录：……”补充进展，或添加相关飞书文档。"
        if self.dify.configured:
            try:
                result = await self.dify.execute(
                    "generate_daily" if kind == "daily" else "generate_weekly",
                    tenant_id=tenant_id, user_id=user_id, facts=facts_context(facts, limit=200),
                    period={"start": start.isoformat(), "end": end.isoformat()},
                    extra={"report_type": kind, "user_timezone": user.get("timezone", settings.feishu_timezone),
                           "project_ownership": self.store.list_project_ownership(tenant_id, user_id)},
                )
                draft_text = (result or {}).get("draft_text") or (result or {}).get("reply")
                if not draft_text:
                    draft_text = local_draft(kind, facts, start, end)
            except Exception:
                logger.exception("Dify draft generation failed")
                draft_text = local_draft(kind, facts, start, end)
                draft_text += "\n\n（AI 服务暂不可用，此版本按已记录事实生成，建议人工检查。）"
        else:
            draft_text = local_draft(kind, facts, start, end)
            if facts:
                draft_text += "\n\n（当前未配置 Dify，以上为基于已记录事实的基础草稿。）"

        target = self.store.get_target(tenant_id, user_id, kind)
        base_hash = ""
        target_doc_id = target["document_id"] if target else ""
        target_block_id = target["block_id"] if target else ""
        if target and self.feishu.configured:
            try:
                block, _revision = await self.feishu.get_block(target_doc_id, target_block_id)
                base_hash = text_hash(block_text(block))
            except Exception:
                logger.exception("could not snapshot writeback target")
        draft = self.store.create_draft(tenant_id, user_id, kind, start.isoformat(), end.isoformat(), draft_text,
                                        base_text_hash=base_hash, target_doc_id=target_doc_id, target_block_id=target_block_id)
        self.store.audit(tenant_id, user_id, "draft_created", draft["id"], {"kind": kind, "facts_count": len(facts)})
        title = "日报" if kind == "daily" else "周报"
        return f"已准备{title}草稿（编号 {draft['id']}），尚未写入正式文档。\n\n{draft_text}\n\n修改：直接回复要调整的内容。确认：回复“确认{title}”。"

    async def edit_draft(self, tenant_id: str, user_id: str, draft: dict[str, Any], instruction: str, model_result: dict[str, Any] | None = None) -> str:
        new_content = ""
        if model_result:
            new_content = str(model_result.get("draft_text") or "")
        if not new_content and self.dify.configured:
            try:
                result = await self.dify.execute("edit_draft", tenant_id=tenant_id, user_id=user_id, user_message=instruction,
                                                 current_draft=draft["content"], extra={"draft_kind": draft["kind"], "draft_id": draft["id"]})
                new_content = str((result or {}).get("draft_text") or "")
            except Exception:
                logger.exception("Dify edit failed")
        if not new_content:
            new_content = self._fallback_edit(draft["content"], instruction)
        updated = self.store.update_draft_content(tenant_id, user_id, draft["id"], new_content)
        self.store.audit(tenant_id, user_id, "draft_edited", draft["id"], {"version": updated["version"]})
        title = "日报" if draft["kind"] == "daily" else "周报"
        return f"{title}草稿已修改（版本 {updated['version']}），仍未写入正式文档。\n\n{new_content}\n\n继续修改可直接回复；确认后回复“确认{title}”。"

    @staticmethod
    def _fallback_edit(content: str, instruction: str) -> str:
        # Safe, intentionally limited edit behavior when no model is configured.
        quoted = re.search(r"(?:把|将)[“\"'](.+?)[”\"'](?:改为|改成|替换为)[“\"'](.+?)[”\"']", instruction)
        if quoted:
            return content.replace(quoted.group(1), quoted.group(2))
        append = re.search(r"(?:补充|加上|增加)(?:一条|内容|说明)?[:：]?\s*(.+)$", instruction)
        if append:
            return content.rstrip() + "\n- " + append.group(1).strip()
        return content.rstrip() + "\n\n【待调整说明】" + instruction + "\n（已保留原稿；当前未配置 AI，以上修改请求尚未自动应用，请配置 Dify 后重试。）"

    async def confirm_draft(self, tenant_id: str, user_id: str, kind: str | None = None) -> str:
        if not kind:
            pending = self.store.list_drafts(tenant_id, user_id, status="pending_confirmation", limit=5)
            kinds = {d["kind"] for d in pending}
            if len(kinds) > 1:
                return "你有日报和周报两份草稿，请分别回复“确认日报”或“确认周报”。"
            if not pending:
                return "没有待确认的草稿。可以先发送“生成日报”或“生成周报”。"
            kind = pending[0]["kind"]
        draft = self.store.latest_pending_draft(tenant_id, user_id, kind)
        if not draft:
            return f"没有待确认的{'日报' if kind == 'daily' else '周报'}草稿。"
        draft = self.store.confirm_draft(tenant_id, user_id, draft["id"])
        self.store.audit(tenant_id, user_id, "draft_confirmed", draft["id"], {"kind": kind})
        if not settings.writeback_enabled:
            return f"已确认草稿 {draft['id']}。当前 WRITEBACK_ENABLED=false，正式文档未被修改。启用安全写回并配置目标文档后，可重新部署；本次草稿已保留为“已确认、待写回”。"
        if not draft.get("target_doc_id") or not draft.get("target_block_id"):
            self.store.mark_draft_result(draft["id"], "write_failed", "未配置目标文档或段落块")
            return "草稿已确认，但未配置这类报告的目标文档/段落块，未执行写回。请先配置目标映射，再重新生成并确认草稿。"
        if not draft.get("base_text_hash"):
            self.store.mark_draft_result(draft["id"], "write_failed", "生成草稿时未能读取目标块，无法建立冲突快照")
            return "草稿已确认，但生成草稿时无法读取目标段落，未执行写回。请检查文档授权和块 ID，然后重新生成草稿。"
        try:
            block, revision = await self.feishu.get_block(draft["target_doc_id"], draft["target_block_id"])
            current_text = block_text(block)
            if text_hash(current_text) != draft["base_text_hash"]:
                self.store.mark_draft_result(draft["id"], "conflict", "目标段落在草稿生成后发生变化")
                self.store.audit(tenant_id, user_id, "writeback_conflict", draft["id"], {"document_id": draft["target_doc_id"], "block_id": draft["target_block_id"]})
                return "检测到目标文档在草稿生成后发生变化。为避免覆盖他人修改，写回已暂停；请重新生成草稿并核对差异。"
            await self.feishu.patch_text_block(draft["target_doc_id"], draft["target_block_id"], draft["content"], revision)
            self.store.mark_draft_result(draft["id"], "published")
            self.store.audit(tenant_id, user_id, "writeback_succeeded", draft["id"], {"document_id": draft["target_doc_id"], "block_id": draft["target_block_id"]})
            return f"已确认并更新目标文档中的指定段落（草稿 {draft['id']}）。其他文档块未被修改。"
        except Exception as exc:
            logger.exception("writeback failed")
            self.store.mark_draft_result(draft["id"], "write_failed", self._short_error(exc))
            return f"草稿已确认，但写回失败，未报告成功。原因：{self._short_error(exc)}。请检查权限和目标块类型后重试。"

    async def sync_source(self, source: dict[str, Any]) -> tuple[int, bool]:
        if not self.feishu.configured:
            raise RuntimeError("未配置飞书应用凭证")
        blocks, revision = await self.feishu.list_document_blocks(source["document_id"])
        text_parts = [block_text(b) for b in blocks]
        text_parts = [t for t in text_parts if t]
        document_text = "\n".join(text_parts)
        digest = content_hash(document_text)
        if digest == source.get("last_content_hash") and source.get("last_content_hash"):
            self.store.update_source_sync(source["id"], digest, revision)
            return 0, False
        if not self.dify.configured:
            raise RuntimeError("尚未配置 Dify Chatflow API Key，无法可靠抽取工作事实")
        result = await self.dify.execute("extract_facts", tenant_id=source["tenant_id"], user_id=source["user_id"],
                                         source_text=document_text, extra={"source_url": source["url"], "source_title": source.get("title", "")})
        facts = (result or {}).get("facts") or []
        count = 0
        for fact in facts:
            content = str(fact.get("content") or "").strip()
            if not content:
                continue
            _saved, created = self.store.add_fact(
                source["tenant_id"], source["user_id"], content,
                occurred_at=fact.get("occurred_at") or None, business=fact.get("business", ""), project=fact.get("project", ""),
                contribution=fact.get("contribution", "background"), status="needs_review" if float(fact.get("confidence", 0.5)) < 0.65 else "recorded",
                confidence=float(fact.get("confidence", 0.5)), source_url=source["url"], source_title=source.get("title", ""),
                source_excerpt=fact.get("source_excerpt", ""),
            )
            count += int(created)
        self.store.update_source_sync(source["id"], digest, revision)
        self.store.audit(source["tenant_id"], source["user_id"], "source_synced", source["id"], {"facts_created": count, "revision": revision})
        return count, bool(count)

    async def discover_scope(self, scope: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.feishu.configured:
            raise RuntimeError("未配置飞书应用凭证")
        files = await self.feishu.list_drive_files(scope["folder_token"])
        discovered: list[dict[str, Any]] = []
        seen_doc_ids: set[str] = set()
        for item in files:
            if item.get("type") != "docx":
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            try:
                document_id = parse_docx_url(url)
            except ValueError:
                continue
            if document_id in seen_doc_ids:
                continue
            seen_doc_ids.add(document_id)
            source = self.store.add_source(scope["tenant_id"], scope["user_id"], url, document_id, title=str(item.get("name") or ""))
            discovered.append(source)
        self.store.update_scope_sync(scope["id"])
        self.store.audit(scope["tenant_id"], scope["user_id"], "scope_discovered", scope["id"], {"docx_count": len(discovered)})
        return discovered

    async def sync_all_sources(self) -> None:
        # Re-scan explicitly authorized folders first, then incrementally sync the resulting docs.
        for scope in self.store.list_source_scopes():
            try:
                await self.discover_scope(scope)
            except Exception as exc:
                logger.warning("scope discovery failed scope_id=%s reason=%s", scope.get("id"), self._short_error(exc))
        if not self.dify.configured:
            return
        for source in self.store.list_sources():
            try:
                await self.sync_source(source)
            except Exception as exc:
                logger.warning("source sync failed source_id=%s reason=%s", source.get("id"), self._short_error(exc))

    async def sync_calendar_for_user(self, tenant_id: str, user_id: str, days_back: int = 7, days_forward: int = 2) -> int:
        user = self.store.get_user(tenant_id, user_id)
        if not user or not user.get("calendar_id"):
            return 0
        tz = ZoneInfo(user.get("timezone") or settings.feishu_timezone)
        now = datetime.now(tz)
        start = int((now - timedelta(days=days_back)).timestamp())
        end = int((now + timedelta(days=days_forward)).timestamp())
        events = await self.feishu.list_calendar_events(user["calendar_id"], start, end)
        count = 0
        for event in events:
            summary = (event.get("summary") or "未命名会议").strip()
            start_data = event.get("start_time") or {}
            timestamp = start_data.get("timestamp")
            if timestamp:
                try:
                    occurred = datetime.fromtimestamp(int(timestamp), tz).date().isoformat()
                except Exception:
                    occurred = now.date().isoformat()
            else:
                occurred = start_data.get("date") or now.date().isoformat()
            description = (event.get("description") or "").strip()
            content = f"日历安排：{summary}。该记录仅表示日程安排，不证明会议已举行或任务已完成。"
            if description:
                content += f" 日程描述：{description[:400]}"
            _fact, created = self.store.add_fact(
                tenant_id, user_id, content, occurred_at=occurred, contribution="background", status="scheduled",
                confidence=0.35, source_url=f"calendar://{user['calendar_id']}/{event.get('event_id','')}",
                source_title=summary, source_excerpt=description[:400],
            )
            count += int(created)
        return count

    async def scheduler_tick(self) -> None:
        for user in self.store.list_users():
            try:
                tz = ZoneInfo(user.get("timezone") or settings.feishu_timezone)
                now = datetime.now(tz)
                today = now.date().isoformat()
                is_weekly_day = now.weekday() == int(user.get("weekly_day", 4))
                daily_time = user.get("daily_time") or settings.default_daily_time
                weekly_time = user.get("weekly_time") or settings.default_weekly_time
                # On a weekly-report day, prepare both reports together at the later configured time.
                target_time = max(daily_time, weekly_time) if is_weekly_day else daily_time
                if now.strftime("%H:%M") < target_time:
                    continue
                need_daily = user.get("last_daily_date") != today
                need_weekly = is_weekly_day and user.get("last_weekly_date") != today
                if not need_daily and not need_weekly:
                    continue
                replies = []
                if need_daily:
                    replies.append(await self.generate_draft(user["tenant_id"], user["user_id"], "daily", target_date=now.date()))
                    self.store.update_schedule_markers(user["tenant_id"], user["user_id"], daily_date=today)
                if need_weekly:
                    replies.append(await self.generate_draft(user["tenant_id"], user["user_id"], "weekly", target_date=now.date()))
                    self.store.update_schedule_markers(user["tenant_id"], user["user_id"], weekly_date=today)
                if self.feishu.configured:
                    # Scheduler has no access to an open_id mapping unless the user has used the bot.
                    # user_id is the Feishu open_id in this MVP.
                    await self.feishu.send_text(user["user_id"], "\n\n──────────\n\n".join(replies))
            except Exception:
                logger.exception("scheduled report failed tenant=%s user=%s", user.get("tenant_id"), user.get("user_id"))

    async def sync_calendar_all_users(self) -> None:
        for user in self.store.list_users():
            if not user.get("calendar_id"):
                continue
            try:
                await self.sync_calendar_for_user(user["tenant_id"], user["user_id"])
            except Exception as exc:
                logger.warning("calendar sync failed tenant=%s user=%s reason=%s", user["tenant_id"], user["user_id"], self._short_error(exc))
