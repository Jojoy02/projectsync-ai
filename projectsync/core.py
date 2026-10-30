from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


def now_iso(tz: str = "Asia/Shanghai") -> str:
    return datetime.now(ZoneInfo(tz)).isoformat(timespec="seconds")


def today_in(tz: str = "Asia/Shanghai") -> date:
    return datetime.now(ZoneInfo(tz)).date()


def normalize_text(value: str) -> str:
    value = re.sub(r"\s+", " ", (value or "").strip().lower())
    return value.strip("。；;，, ")


def content_hash(value: str) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def text_hash(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def parse_docx_url(url: str) -> str:
    """Accept only Feishu/Lark document URLs and return a /docx/<token> token."""
    from urllib.parse import urlparse
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    allowed = (host == "feishu.cn" or host.endswith(".feishu.cn") or host == "larksuite.com" or host.endswith(".larksuite.com") or host == "larkoffice.com" or host.endswith(".larkoffice.com"))
    if parsed.scheme != "https" or not allowed:
        raise ValueError("仅支持 https 的飞书/Lark 链接。")
    match = re.search(r"/docx/([A-Za-z0-9_-]+)", parsed.path)
    if not match:
        raise ValueError("目前仅支持新版云文档链接（路径包含 /docx/<document_id>）；知识库链接请先复制实际文档链接。")
    return match.group(1)



def parse_folder_url(url: str) -> str:
    """Extract a Feishu Drive folder token from an authorized folder URL."""
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    allowed = (host == "feishu.cn" or host.endswith(".feishu.cn") or host == "larksuite.com" or host.endswith(".larksuite.com") or host == "larkoffice.com" or host.endswith(".larkoffice.com"))
    if parsed.scheme != "https" or not allowed:
        raise ValueError("仅支持 https 的飞书/Lark 文件夹链接。")
    query = parse_qs(parsed.query)
    if query.get("folder_token"):
        return query["folder_token"][0]
    match = re.search(r"/drive/folder/([A-Za-z0-9_-]+)", parsed.path)
    if match:
        return match.group(1)
    raise ValueError("未能从链接中识别文件夹 token。请复制飞书云空间中的文件夹链接。")

def looks_like_confirm(text: str) -> tuple[bool, str | None]:
    raw = (text or "").strip()
    if re.search(r"^(确认|发布|写回)(日报|日总结)$", raw):
        return True, "daily"
    if re.search(r"^(确认|发布|写回)(周报|周总结)$", raw):
        return True, "weekly"
    if re.fullmatch(r"(确认|发布|写回)\s*", raw):
        return True, None
    return False, None


def looks_like_daily(text: str) -> bool:
    return bool(re.search(r"(生成|准备|查看|写)\s*(一下)?\s*(今天|今日)?\s*(的)?\s*(日报|日总结)|^(日报|日总结)$", text.strip()))


def looks_like_weekly(text: str) -> bool:
    return bool(re.search(r"(生成|准备|查看|写)\s*(一下)?\s*(本周|这周)?\s*(的)?\s*(周报|周总结)|^(周报|周总结)$", text.strip()))


def looks_like_help(text: str) -> bool:
    return text.strip().lower() in {"帮助", "help", "/help", "你能做什么", "功能"}


def looks_like_add_doc(text: str) -> str | None:
    match = re.search(r"(?:添加|关联|同步|读取)文档\s*[:：]?\s*(https://\S+)", text.strip())
    return match.group(1).rstrip("，。；;)") if match else None


def looks_like_add_scope(text: str) -> str | None:
    match = re.search(r"(?:添加|关联|同步)资料范围\s*[:：]?\s*(https://\S+)", text.strip())
    return match.group(1).rstrip("，。；;)") if match else None


def looks_like_record(text: str) -> str | None:
    match = re.match(r"^(?:记录|进展|工作记录|新增进展)\s*[:：]\s*(.+)$", text.strip(), re.S)
    return match.group(1).strip() if match else None


def looks_like_edit(text: str) -> bool:
    return bool(re.search(r"(修改|改成|改为|调整|补充|删除|去掉|精简|展开|换成|不要写|加上|移除)", text))


def period_for(kind: str, today: date) -> tuple[date, date]:
    if kind == "daily":
        return today, today
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


def local_draft(kind: str, facts: list[dict[str, Any]], start: date, end: date) -> str:
    label = "日报" if kind == "daily" else "周报"
    if not facts:
        return f"{label}（{start.isoformat()} 至 {end.isoformat()}）\n\n本期暂无足够的工作记录可供核验。请补充实际进展后再确认。"
    grouped: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        key = fact.get("business") or fact.get("project") or "其他工作"
        grouped.setdefault(key, []).append(fact)
    lines = [f"{label}（{start.isoformat()} 至 {end.isoformat()}）", ""]
    for group, items in grouped.items():
        lines.append(f"【{group}】")
        for item in items:
            content = item.get("content", "").strip()
            contribution = item.get("contribution", "completed")
            prefix = {"completed": "完成", "coordinated": "协调", "followed_up": "跟进", "background": "相关事项"}.get(contribution, "进展")
            if content and not content.startswith(("完成", "推进", "协调", "跟进", "参与", "确认", "处理", "输出", "提交", "开展")):
                content = f"{prefix}{content}"
            lines.append(f"- {content}")
        lines.append("")
    if kind == "weekly":
        lines.extend(["【后续计划】", "- 请根据未完成任务和已确认承诺补充下周计划。"])
    return "\n".join(lines).strip()


def facts_context(facts: list[dict[str, Any]], limit: int = 50) -> list[dict[str, Any]]:
    result = []
    for fact in facts[-limit:]:
        result.append({k: fact.get(k) for k in ("id", "content", "occurred_at", "business", "project", "contribution", "status", "confidence", "source_url", "source_excerpt")})
    return result


def fallback_query(text: str, facts: list[dict[str, Any]]) -> str:
    projects: dict[str, int] = {}
    businesses: dict[str, int] = {}
    for f in facts:
        if f.get("project"):
            projects[f["project"]] = projects.get(f["project"], 0) + 1
        if f.get("business"):
            businesses[f["business"]] = businesses.get(f["business"], 0) + 1
    if re.search(r"项目|跟进|负责", text):
        if projects:
            return "最近记录的项目：\n" + "\n".join(f"- {name}（{count} 条工作记录）" for name, count in projects.items())
        if businesses:
            return "目前有工作记录，但尚未可靠关联具体项目：\n" + "\n".join(f"- {name}（{count} 条记录）" for name, count in businesses.items())
    if facts:
        return "最近的工作记录：\n" + "\n".join(f"- {f.get('occurred_at','')}: {f.get('content','')}" for f in facts[-8:])
    return "目前还没有足够的工作记录。你可以直接发送“记录：完成了什么”，或发送“添加文档 https://.../docx/...”关联飞书云文档。"
