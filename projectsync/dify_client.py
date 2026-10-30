from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import httpx

from .config import settings


SYSTEM_PROMPT = """你是 ProjectSync AI 的工作信息整理引擎。你的目标是识别个人实际工作、关联业务与项目、生成可核验的日报/周报，而不是替用户编造业绩。

输入是一段 JSON，包含 task、user_message、facts、current_draft、period、source_text 等字段。必须只返回一个合法 JSON 对象，不要 Markdown 代码围栏，不要附加解释。所有事实以输入证据为准；缺失信息写空字符串或列入 needs_review，不得猜测。

核心规则：
1. 先识别当前用户实际完成、推动/协调、参与/跟进的事项，再按业务与项目分类。
2. 同一工作事实可以关联业务和项目，但只能计数一次。
3. 团队整体进展不等于当前用户的个人成果；日历中的会议安排不能证明会议已举行或任务已完成。
4. 证据不足时使用谨慎表述，并标记待核验；不要将计划写成已完成。
5. 日报和周报沿用已有汇报结构；周报不是简单拼接日报。
6. 自然语言修改只修改指定草稿，不要擅自修改事实库或其他草稿。
7. 生成的草稿需要用户确认；禁止声称已经发布或写入在线文档。

按 task 输出：
- classify：{"intent":"record_fact|generate_daily|generate_weekly|edit_draft|query|help|other","reply":"...","fact":{"content":"...","occurred_at":"YYYY-MM-DD","business":"...","project":"...","contribution":"completed|coordinated|followed_up|background","confidence":0.0,"source_excerpt":"..."},"draft_text":"..."}
- extract_facts：{"facts":[{"content":"...","occurred_at":"YYYY-MM-DD","business":"...","project":"...","contribution":"completed|coordinated|followed_up|background","confidence":0.0,"source_excerpt":"..."}]}
- generate_daily 或 generate_weekly：{"draft_text":"完整可展示的草稿文本","reply":"简短说明","needs_review":["..."],"used_fact_ids":["..."]}
- edit_draft：{"draft_text":"修改后的完整草稿","reply":"已按要求修改的简短说明","needs_review":["..."]}
- query：{"reply":"基于事实的回答","needs_review":["..."]}

如果用户只发送了一条工作进展，将其识别为 record_fact；如果是在询问项目/待办/历史进展，使用 query；如果当前草稿存在且用户要求改写，则使用 edit_draft。输出 JSON 必须可解析。"""


def parse_json_answer(answer: str) -> dict[str, Any] | None:
    if not answer:
        return None
    text = answer.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None


class DifyClient:
    def __init__(self):
        self.base_url = settings.dify_base_url
        self.api_key = settings.dify_app_api_key
        self.timeout = settings.dify_timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def execute(self, task: str, *, tenant_id: str, user_id: str, user_message: str = "",
                      facts: list[dict[str, Any]] | None = None, current_draft: str = "",
                      period: dict[str, str] | None = None, source_text: str = "",
                      extra: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not self.configured:
            return None
        payload_obj = {
            "task": task,
            "user_message": user_message,
            "facts": facts or [],
            "current_draft": current_draft,
            "period": period or {},
            "source_text": source_text[:30000],
            "extra": extra or {},
        }
        query = "请根据系统规则处理以下输入，并严格输出 JSON：\n" + json.dumps(payload_obj, ensure_ascii=False)
        pseudonymous_user = hashlib.sha256(f"{tenant_id}:{user_id}".encode("utf-8")).hexdigest()[:32]
        payload = {"inputs": {}, "query": query, "response_mode": "blocking", "user": pseudonymous_user}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/v1/chat-messages", headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        if body.get("status") == "failed" or body.get("code"):
            raise RuntimeError(f"Dify 调用失败：{body.get('message') or body.get('code')}")
        answer = body.get("answer", "")
        parsed = parse_json_answer(answer)
        if parsed is not None:
            return parsed
        # Fail safely: do not interpret arbitrary prose as an action.
        return {"intent": "other", "reply": str(answer).strip() or "暂时无法解析模型输出，请重试。", "raw_answer": str(answer)}
