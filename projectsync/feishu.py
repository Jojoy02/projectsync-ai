from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .config import settings


class FeishuAPIError(RuntimeError):
    pass


class FeishuClient:
    def __init__(self):
        self.base = settings.feishu_api_base
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self._token = ""
        self._token_expiry = 0.0
        self.timeout = settings.http_timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.app_secret)

    async def tenant_token(self) -> str:
        if not self.configured:
            raise FeishuAPIError("尚未配置 FEISHU_APP_ID / FEISHU_APP_SECRET")
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(f"{self.base}/auth/v3/tenant_access_token/internal", json={"app_id": self.app_id, "app_secret": self.app_secret})
            r.raise_for_status()
            data = r.json()
        if data.get("code", 0) != 0 or not data.get("tenant_access_token"):
            raise FeishuAPIError(f"获取飞书 tenant_access_token 失败：{data.get('msg', data)}")
        self._token = data["tenant_access_token"]
        self._token_expiry = time.time() + int(data.get("expire", 7200))
        return self._token

    async def request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        token = await self.tenant_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.request(method, f"{self.base}{path}", params=params, json=json_body, headers=headers)
            r.raise_for_status()
            data = r.json()
        if data.get("code", 0) != 0:
            raise FeishuAPIError(f"飞书 API 返回错误：{data.get('code')} {data.get('msg', '')}")
        return data.get("data", {})

    async def send_text(self, open_id: str, text: str) -> None:
        if not open_id:
            raise FeishuAPIError("消息接收者 open_id 为空")
        await self.request("POST", "/im/v1/messages", params={"receive_id_type": "open_id"}, json_body={
            "receive_id": open_id,
            "msg_type": "text",
            "content": json.dumps({"text": text[:4000]}, ensure_ascii=False),
        })

    async def list_document_blocks(self, document_id: str) -> tuple[list[dict[str, Any]], str]:
        items: list[dict[str, Any]] = []
        page_token = ""
        revision = ""
        while True:
            params: dict[str, Any] = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            data = await self.request("GET", f"/docx/v1/documents/{document_id}/blocks", params=params)
            items.extend(data.get("items", []))
            revision = str(data.get("document_revision_id") or revision)
            if not data.get("has_more"):
                break
            page_token = data.get("page_token", "")
            if not page_token:
                break
        return items, revision

    async def get_block(self, document_id: str, block_id: str) -> tuple[dict[str, Any], str]:
        data = await self.request("GET", f"/docx/v1/documents/{document_id}/blocks/{block_id}")
        block = data.get("block") or data
        revision = str(data.get("document_revision_id") or "")
        return block, revision

    async def patch_text_block(self, document_id: str, block_id: str, text: str, revision: str = "") -> dict[str, Any]:
        block, current_revision = await self.get_block(document_id, block_id)
        if block.get("block_type") != 2 and "text" not in block:
            raise FeishuAPIError("目标块不是普通文本块。为避免破坏标题或复杂结构，已停止写回。请将目标映射到专用文本块。")
        params = {"document_revision_id": revision or current_revision} if (revision or current_revision) else None
        body = {"update_text_elements": {"elements": [{"text_run": {"content": text}}]}}
        return await self.request("PATCH", f"/docx/v1/documents/{document_id}/blocks/{block_id}", params=params, json_body=body)

    async def list_drive_files(self, folder_token: str, max_files: int = 500, max_depth: int = 3) -> list[dict[str, Any]]:
        """Walk a user-authorized Drive folder scope and return its file metadata."""
        result: list[dict[str, Any]] = []
        seen: set[str] = set()

        async def walk(token: str, depth: int) -> None:
            if token in seen or len(result) >= max_files:
                return
            seen.add(token)
            page_token = ""
            while len(result) < max_files:
                params: dict[str, Any] = {"folder_token": token, "page_size": 200, "order_by": "EditedTime", "direction": "DESC"}
                if page_token:
                    params["page_token"] = page_token
                data = await self.request("GET", "/drive/v1/files", params=params)
                files = data.get("files", [])
                for item in files:
                    result.append(item)
                    if len(result) >= max_files:
                        break
                if depth < max_depth:
                    for item in files:
                        if item.get("type") == "folder" and item.get("token") and item.get("token") not in seen:
                            await walk(item["token"], depth + 1)
                            if len(result) >= max_files:
                                break
                if not data.get("has_more") or not data.get("page_token"):
                    break
                page_token = data["page_token"]

        await walk(folder_token, 0)
        return result[:max_files]

    async def list_calendar_events(self, calendar_id: str, start_epoch: int, end_epoch: int) -> list[dict[str, Any]]:
        data = await self.request("GET", f"/calendar/v4/calendars/{calendar_id}/events", params={
            "start_time": str(start_epoch), "end_time": str(end_epoch), "page_size": 500, "user_id_type": "open_id"
        })
        return data.get("items", [])


def extract_document_id(url: str) -> str:
    from .core import parse_docx_url
    return parse_docx_url(url)


def block_text(block: dict[str, Any]) -> str:
    """Flatten common Docx block types into plain text for review and hashing."""
    chunks: list[str] = []
    block_type = block.get("block_type")
    key_map = {
        1: "page", 2: "text", 3: "heading1", 4: "heading2", 5: "heading3", 6: "heading4",
        7: "heading5", 8: "heading6", 9: "heading7", 10: "heading8", 11: "heading9",
        12: "bullet", 13: "ordered", 14: "code", 15: "quote", 16: "todo",
    }
    keys = [key_map.get(block_type, "text"), "text", "paragraph", "heading1", "heading2", "heading3", "bullet", "ordered", "code", "quote", "todo"]
    for key in dict.fromkeys(keys):
        data = block.get(key)
        if not isinstance(data, dict):
            continue
        for element in data.get("elements", []):
            run = element.get("text_run") or {}
            if run.get("content"):
                chunks.append(str(run["content"]))
        if chunks:
            break
    return "".join(chunks).strip()
