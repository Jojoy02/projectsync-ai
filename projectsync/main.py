from __future__ import annotations

import base64
import hashlib
import json
import logging
import struct
from contextlib import asynccontextmanager
from typing import Any

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except ImportError:  # optional in minimal test environments; install requirements.txt for scheduled runs
    AsyncIOScheduler = None  # type: ignore[assignment,misc]
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .config import settings
from .core import parse_docx_url
from .dify_client import DifyClient
from .feishu import FeishuClient, block_text
from .service import ProjectSyncService
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("projectsync.api")

store = Store()
service = ProjectSyncService(store=store)
scheduler = AsyncIOScheduler(timezone=settings.feishu_timezone) if AsyncIOScheduler else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.enable_scheduler and scheduler is not None:
        scheduler.add_job(service.scheduler_tick, "interval", minutes=1, id="report-scheduler", replace_existing=True, max_instances=1, coalesce=True)
        scheduler.add_job(service.sync_all_sources, "interval", minutes=15, id="source-sync", replace_existing=True, max_instances=1, coalesce=True)
        scheduler.add_job(service.sync_calendar_all_users, "interval", minutes=30, id="calendar-sync", replace_existing=True, max_instances=1, coalesce=True)
        scheduler.start()
        logger.info("scheduler started")
    elif settings.enable_scheduler:
        logger.warning("APScheduler is not installed; background schedules are disabled")
    yield
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="ProjectSync AI", version="0.1.0", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)


class TargetRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1, description="飞书用户 open_id")
    report_type: str = Field(pattern="^(daily|weekly)$")
    document_url: str = Field(min_length=1)
    block_id: str = Field(min_length=1)


class IngestRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=8000)
    occurred_at: str | None = None
    business: str = ""
    project: str = ""
    contribution: str = "completed"
    source_url: str = ""
    source_excerpt: str = ""


class UserSettingsRequest(BaseModel):
    tenant_id: str
    user_id: str
    timezone: str | None = None
    daily_time: str | None = None
    weekly_day: int | None = Field(default=None, ge=0, le=6)
    weekly_time: str | None = None
    calendar_id: str | None = None


def require_admin(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> None:
    if not settings.admin_token or not x_admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Missing or invalid X-Admin-Token")


def _decrypt_feishu_payload(encrypted: str) -> dict[str, Any]:
    if not settings.feishu_encrypt_key:
        raise HTTPException(status_code=400, detail="Encrypted Feishu event received, but FEISHU_ENCRYPT_KEY is not configured")
    try:
        key = hashlib.sha256(settings.feishu_encrypt_key.encode("utf-8")).digest()
        raw = base64.b64decode(encrypted)
        cipher = Cipher(algorithms.AES(key), modes.CBC(key[:16]))
        decryptor = cipher.decryptor()
        padded = decryptor.update(raw) + decryptor.finalize()
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        plain = unpadder.update(padded) + unpadder.finalize()
        # Feishu encrypted payload: random(16) + length(4, big endian) + JSON bytes.
        if len(plain) >= 20:
            size = struct.unpack(">I", plain[16:20])[0]
            candidate = plain[20:20 + size]
            if candidate.startswith(b"{"):
                plain = candidate
        return json.loads(plain.decode("utf-8"))
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("failed to decrypt Feishu callback: %s", exc.__class__.__name__)
        raise HTTPException(status_code=400, detail="Unable to decrypt Feishu callback") from exc


def _validate_feishu_token(body: dict[str, Any]) -> None:
    expected = settings.feishu_verification_token
    if not expected:
        if settings.app_env == "production":
            raise HTTPException(status_code=503, detail="FEISHU_VERIFICATION_TOKEN is required in production")
        return
    token = body.get("token") or (body.get("header") or {}).get("token")
    if token != expected:
        raise HTTPException(status_code=403, detail="Invalid Feishu verification token")


def _event_text(message: dict[str, Any]) -> str:
    if message.get("message_type") != "text":
        return ""
    raw = message.get("content", "")
    try:
        obj = json.loads(raw) if isinstance(raw, str) else raw
        return str(obj.get("text", "")).strip()
    except Exception:
        return str(raw).strip()


async def _process_feishu_message(tenant_id: str, open_id: str, message_id: str, text: str) -> None:
    try:
        reply = await service.handle_message(tenant_id, open_id, text)
        await service.feishu.send_text(open_id, reply)
    except Exception:
        logger.exception("failed to process Feishu message id=%s", message_id)
        try:
            await service.feishu.send_text(open_id, "处理失败，未执行正式文档写回。请稍后重试；如果持续失败，请联系管理员查看服务日志。")
        except Exception:
            logger.exception("failed to send Feishu error message")
    finally:
        store.mark_message_processed(message_id)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "projectsync-ai",
        "dify_configured": service.dify.configured,
        "feishu_configured": service.feishu.configured,
        "scheduler_enabled": bool(settings.enable_scheduler and scheduler is not None),
        "writeback_enabled": settings.writeback_enabled,
    }


@app.post("/webhooks/feishu/events")
async def feishu_event(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid event body")
    if body.get("encrypt"):
        body = _decrypt_feishu_payload(body["encrypt"])
    if body.get("type") == "url_verification" or "challenge" in body:
        _validate_feishu_token(body)
        return {"challenge": body.get("challenge", "")}
    _validate_feishu_token(body)
    header = body.get("header") or {}
    event = body.get("event") or {}
    sender = event.get("sender") or {}
    message = event.get("message") or {}
    if sender.get("sender_type") == "bot":
        return {"code": 0, "msg": "ignored bot message"}
    open_id = ((sender.get("sender_id") or {}).get("open_id") or "").strip()
    tenant_id = str(header.get("tenant_key") or sender.get("tenant_key") or "").strip()
    message_id = str(message.get("message_id") or "").strip()
    text = _event_text(message)
    if not open_id or not tenant_id or not message_id:
        return {"code": 0, "msg": "missing sender, tenant, or message id"}
    if not text:
        background_tasks.add_task(_process_feishu_message, tenant_id, open_id, message_id, "")
        return {"code": 0, "msg": "unsupported message type"}
    if not store.claim_message(message_id):
        return {"code": 0, "msg": "duplicate event ignored"}
    background_tasks.add_task(_process_feishu_message, tenant_id, open_id, message_id, text)
    return {"code": 0, "msg": "accepted"}


@app.get("/api/status", dependencies=[Depends(require_admin)])
async def status() -> dict[str, Any]:
    return await health()


@app.get("/api/users", dependencies=[Depends(require_admin)])
async def list_users() -> dict[str, Any]:
    return {"items": store.list_users()}


@app.get("/api/scopes", dependencies=[Depends(require_admin)])
async def list_scopes(tenant_id: str | None = None, user_id: str | None = None) -> dict[str, Any]:
    return {"items": store.list_source_scopes(tenant_id, user_id)}


@app.get("/api/projects/ownership", dependencies=[Depends(require_admin)])
async def list_project_ownership(tenant_id: str, user_id: str) -> dict[str, Any]:
    return {"items": store.list_project_ownership(tenant_id, user_id)}


@app.get("/api/docs/blocks", dependencies=[Depends(require_admin)])
async def get_document_blocks(url: str = Query(..., description="飞书新版文档 URL")) -> dict[str, Any]:
    try:
        document_id = parse_docx_url(url)
        blocks, revision = await service.feishu.list_document_blocks(document_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = []
    for block in blocks:
        text = block_text(block)
        if text:
            result.append({"block_id": block.get("block_id", ""), "block_type": block.get("block_type"), "text": text[:1000]})
    return {"document_id": document_id, "document_revision_id": revision, "text_blocks": result}


@app.post("/api/targets", dependencies=[Depends(require_admin)])
async def set_target(body: TargetRequest) -> dict[str, Any]:
    try:
        document_id = parse_docx_url(body.document_url)
        # Validate target block before saving the mapping.
        block, _revision = await service.feishu.get_block(document_id, body.block_id)
        if block.get("block_type") != 2 and "text" not in block:
            raise ValueError("目标块必须是普通文本块；请勿将标题、表格或整篇文档设为写回目标。")
        saved = store.upsert_target(body.tenant_id, body.user_id, body.report_type, document_id, body.block_id, body.document_url)
        return {"ok": True, "target": saved, "preview_text": block_text(block)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/ingest", dependencies=[Depends(require_admin)])
async def ingest_fact(body: IngestRequest) -> dict[str, Any]:
    store.ensure_user(body.tenant_id, body.user_id, timezone=settings.feishu_timezone,
                      daily_time=settings.default_daily_time, weekly_day=settings.default_weekly_day,
                      weekly_time=settings.default_weekly_time, calendar_id=settings.feishu_calendar_id)
    try:
        fact, created = store.add_fact(body.tenant_id, body.user_id, body.content, occurred_at=body.occurred_at,
                                       business=body.business, project=body.project, contribution=body.contribution,
                                       source_url=body.source_url, source_excerpt=body.source_excerpt)
        return {"ok": True, "created": created, "fact": fact}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/facts", dependencies=[Depends(require_admin)])
async def list_facts(tenant_id: str, user_id: str, start: str | None = None, end: str | None = None) -> dict[str, Any]:
    return {"items": store.list_facts(tenant_id, user_id, start, end, limit=500)}


@app.post("/api/users/settings", dependencies=[Depends(require_admin)])
async def update_user_settings(body: UserSettingsRequest) -> dict[str, Any]:
    user = store.ensure_user(body.tenant_id, body.user_id, timezone=settings.feishu_timezone,
                             daily_time=settings.default_daily_time, weekly_day=settings.default_weekly_day,
                             weekly_time=settings.default_weekly_time, calendar_id=settings.feishu_calendar_id)
    fields = body.model_dump(exclude={"tenant_id", "user_id"}, exclude_none=True)
    if "timezone" in fields:
        from zoneinfo import ZoneInfo
        try: ZoneInfo(fields["timezone"])
        except Exception as exc: raise HTTPException(status_code=400, detail="Invalid IANA timezone") from exc
    for key in ("daily_time", "weekly_time"):
        if key in fields and (len(fields[key]) != 5 or fields[key][2] != ":"):
            raise HTTPException(status_code=400, detail=f"{key} must use HH:MM")
    return {"ok": True, "user": store.update_user_settings(body.tenant_id, body.user_id, **fields)}


@app.post("/api/sync/sources", dependencies=[Depends(require_admin)])
async def sync_sources() -> dict[str, str]:
    await service.sync_all_sources()
    return {"ok": "true", "message": "Source sync completed; check application logs for per-source failures."}


@app.post("/api/sync/calendar", dependencies=[Depends(require_admin)])
async def sync_calendar() -> dict[str, str]:
    await service.sync_calendar_all_users()
    return {"ok": "true", "message": "Calendar sync completed; check application logs for per-user failures."}


@app.post("/api/scheduler/run", dependencies=[Depends(require_admin)])
async def run_scheduler() -> dict[str, str]:
    await service.scheduler_tick()
    return {"ok": "true", "message": "Scheduler tick executed."}


@app.post("/api/test/dify", dependencies=[Depends(require_admin)])
async def test_dify() -> dict[str, Any]:
    if not service.dify.configured:
        raise HTTPException(status_code=400, detail="DIFY_APP_API_KEY is not configured")
    try:
        result = await service.dify.execute("classify", tenant_id="test-tenant", user_id="test-user", user_message="记录：完成了接口联调")
        return {"ok": True, "result": result}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
