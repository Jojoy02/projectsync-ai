from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .core import content_hash, now_iso
from .config import settings


class Store:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path or settings.db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def conn(self):
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def init_db(self) -> None:
        with self.conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS users (
              tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, display_name TEXT DEFAULT '',
              timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai', daily_time TEXT NOT NULL DEFAULT '18:00',
              weekly_day INTEGER NOT NULL DEFAULT 4, weekly_time TEXT NOT NULL DEFAULT '18:00',
              calendar_id TEXT DEFAULT '', last_daily_date TEXT DEFAULT '', last_weekly_date TEXT DEFAULT '',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              PRIMARY KEY (tenant_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS facts (
              id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
              content TEXT NOT NULL, occurred_at TEXT NOT NULL, business TEXT DEFAULT '', project TEXT DEFAULT '',
              contribution TEXT NOT NULL DEFAULT 'completed', status TEXT NOT NULL DEFAULT 'recorded',
              confidence REAL NOT NULL DEFAULT 0.65, source_url TEXT DEFAULT '', source_title TEXT DEFAULT '',
              source_excerpt TEXT DEFAULT '', source_refs_json TEXT NOT NULL DEFAULT '[]',
              content_hash TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              UNIQUE(tenant_id, user_id, content_hash)
            );
            CREATE INDEX IF NOT EXISTS idx_facts_user_date ON facts(tenant_id,user_id,occurred_at);
            CREATE TABLE IF NOT EXISTS sources (
              id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, url TEXT NOT NULL,
              document_id TEXT NOT NULL, title TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
              last_content_hash TEXT DEFAULT '', last_revision TEXT DEFAULT '', last_synced_at TEXT DEFAULT '',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              UNIQUE(tenant_id,user_id,url)
            );
            CREATE TABLE IF NOT EXISTS drafts (
              id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, kind TEXT NOT NULL,
              period_start TEXT NOT NULL, period_end TEXT NOT NULL, content TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending_confirmation', version INTEGER NOT NULL DEFAULT 1,
              base_text_hash TEXT DEFAULT '', target_doc_id TEXT DEFAULT '', target_block_id TEXT DEFAULT '',
              confirmed_at TEXT DEFAULT '', written_at TEXT DEFAULT '', last_error TEXT DEFAULT '',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_drafts_user_status ON drafts(tenant_id,user_id,status,created_at);
            CREATE TABLE IF NOT EXISTS targets (
              id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, report_type TEXT NOT NULL,
              document_id TEXT NOT NULL, block_id TEXT NOT NULL, document_url TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              UNIQUE(tenant_id,user_id,report_type)
            );
            CREATE TABLE IF NOT EXISTS source_scopes (
              id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, folder_token TEXT NOT NULL,
              folder_url TEXT NOT NULL, title TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
              last_synced_at TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              UNIQUE(tenant_id,user_id,folder_token)
            );
            CREATE TABLE IF NOT EXISTS project_ownership (
              id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, project_name TEXT NOT NULL,
              business TEXT DEFAULT '', owner_name TEXT DEFAULT '', owner_user_id TEXT DEFAULT '',
              role TEXT NOT NULL DEFAULT 'contributor', note TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              UNIQUE(tenant_id,user_id,project_name)
            );
            CREATE TABLE IF NOT EXISTS processed_messages (
              message_id TEXT PRIMARY KEY, received_at TEXT NOT NULL, processed_at TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS audit_log (
              id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, action TEXT NOT NULL,
              entity_id TEXT DEFAULT '', details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            );
            """)
            # Safe, additive migration for databases created by an earlier build.
            columns = {row[1] for row in c.execute("PRAGMA table_info(users)").fetchall()}
            if "calendar_id" not in columns:
                c.execute("ALTER TABLE users ADD COLUMN calendar_id TEXT DEFAULT ''")

    def ensure_user(self, tenant_id: str, user_id: str, timezone: str = "Asia/Shanghai", daily_time: str = "18:00", weekly_day: int = 4, weekly_time: str = "18:00", calendar_id: str = "") -> dict[str, Any]:
        now = now_iso(timezone or "Asia/Shanghai")
        with self.conn() as c:
            c.execute("""INSERT INTO users(tenant_id,user_id,timezone,daily_time,weekly_day,weekly_time,calendar_id,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id,user_id) DO NOTHING""",
                (tenant_id, user_id, timezone, daily_time, weekly_day, weekly_time, calendar_id, now, now))
            row = c.execute("SELECT * FROM users WHERE tenant_id=? AND user_id=?", (tenant_id, user_id)).fetchone()
            return dict(row)

    def get_user(self, tenant_id: str, user_id: str) -> dict[str, Any] | None:
        with self.conn() as c:
            row = c.execute("SELECT * FROM users WHERE tenant_id=? AND user_id=?", (tenant_id, user_id)).fetchone()
            return dict(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM users").fetchall()]

    def update_user_settings(self, tenant_id: str, user_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"timezone", "daily_time", "weekly_day", "weekly_time", "calendar_id", "display_name"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return self.get_user(tenant_id, user_id) or {}
        now = now_iso(fields.get("timezone") or "Asia/Shanghai")
        assignments = ",".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [now, tenant_id, user_id]
        with self.conn() as c:
            c.execute(f"UPDATE users SET {assignments},updated_at=? WHERE tenant_id=? AND user_id=?", values)
        return self.get_user(tenant_id, user_id) or {}

    def add_fact(self, tenant_id: str, user_id: str, content: str, *, occurred_at: str | None = None,
                 business: str = "", project: str = "", contribution: str = "completed", status: str = "recorded",
                 confidence: float = 0.65, source_url: str = "", source_title: str = "", source_excerpt: str = "") -> tuple[dict[str, Any], bool]:
        content = (content or "").strip()
        if not content:
            raise ValueError("工作事实内容不能为空")
        timestamp = now_iso()
        occurred_at = occurred_at or timestamp[:10]
        digest = content_hash(f"{occurred_at}|{content}")
        ref = {"url": source_url, "title": source_title, "excerpt": source_excerpt} if (source_url or source_title or source_excerpt) else None
        with self.conn() as c:
            existing = c.execute("SELECT * FROM facts WHERE tenant_id=? AND user_id=? AND content_hash=?", (tenant_id, user_id, digest)).fetchone()
            if existing:
                refs = json.loads(existing["source_refs_json"] or "[]")
                if ref and ref not in refs:
                    refs.append(ref)
                    c.execute("UPDATE facts SET source_refs_json=?,updated_at=? WHERE id=?", (json.dumps(refs, ensure_ascii=False), timestamp, existing["id"]))
                row = c.execute("SELECT * FROM facts WHERE id=?", (existing["id"],)).fetchone()
                return self._fact_row(row), False
            fact_id = str(uuid.uuid4())
            c.execute("""INSERT INTO facts(id,tenant_id,user_id,content,occurred_at,business,project,contribution,status,confidence,source_url,source_title,source_excerpt,source_refs_json,content_hash,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fact_id, tenant_id, user_id, content, occurred_at, business, project, contribution, status,
                 max(0.0, min(float(confidence), 1.0)), source_url, source_title, source_excerpt,
                 json.dumps([ref] if ref else [], ensure_ascii=False), digest, timestamp, timestamp))
            row = c.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone()
            return self._fact_row(row), True

    @staticmethod
    def _fact_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        data["source_refs"] = json.loads(data.pop("source_refs_json", "[]") or "[]")
        return data

    def list_facts(self, tenant_id: str, user_id: str, start: str | None = None, end: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT * FROM facts WHERE tenant_id=? AND user_id=?"
        params: list[Any] = [tenant_id, user_id]
        if start:
            sql += " AND occurred_at>=?"; params.append(start)
        if end:
            sql += " AND occurred_at<=?"; params.append(end)
        sql += " ORDER BY occurred_at ASC, created_at ASC LIMIT ?"; params.append(limit)
        with self.conn() as c:
            return [self._fact_row(r) for r in c.execute(sql, params).fetchall()]

    def add_source(self, tenant_id: str, user_id: str, url: str, document_id: str, title: str = "") -> dict[str, Any]:
        now = now_iso()
        with self.conn() as c:
            existing = c.execute("SELECT * FROM sources WHERE tenant_id=? AND user_id=? AND url=?", (tenant_id,user_id,url)).fetchone()
            if existing:
                c.execute("UPDATE sources SET active=1,document_id=?,title=?,updated_at=? WHERE id=?", (document_id,title or existing["title"],now,existing["id"]))
                row = c.execute("SELECT * FROM sources WHERE id=?", (existing["id"],)).fetchone()
            else:
                sid = str(uuid.uuid4())
                c.execute("INSERT INTO sources(id,tenant_id,user_id,url,document_id,title,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (sid,tenant_id,user_id,url,document_id,title,now,now))
                row = c.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
            return dict(row)

    def list_sources(self, tenant_id: str | None = None, user_id: str | None = None, active_only: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM sources WHERE 1=1"; params: list[Any] = []
        if tenant_id is not None: sql += " AND tenant_id=?"; params.append(tenant_id)
        if user_id is not None: sql += " AND user_id=?"; params.append(user_id)
        if active_only: sql += " AND active=1"
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def add_source_scope(self, tenant_id: str, user_id: str, folder_url: str, folder_token: str, title: str = "") -> dict[str, Any]:
        now = now_iso()
        with self.conn() as c:
            old = c.execute("SELECT id FROM source_scopes WHERE tenant_id=? AND user_id=? AND folder_token=?", (tenant_id,user_id,folder_token)).fetchone()
            scope_id = old["id"] if old else str(uuid.uuid4())
            c.execute("""INSERT INTO source_scopes(id,tenant_id,user_id,folder_token,folder_url,title,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id,user_id,folder_token) DO UPDATE SET folder_url=excluded.folder_url,title=excluded.title,active=1,updated_at=excluded.updated_at""",
                (scope_id,tenant_id,user_id,folder_token,folder_url,title,now,now))
            return dict(c.execute("SELECT * FROM source_scopes WHERE id=?", (scope_id,)).fetchone())

    def list_source_scopes(self, tenant_id: str | None = None, user_id: str | None = None, active_only: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM source_scopes WHERE 1=1"; params: list[Any] = []
        if tenant_id is not None: sql += " AND tenant_id=?"; params.append(tenant_id)
        if user_id is not None: sql += " AND user_id=?"; params.append(user_id)
        if active_only: sql += " AND active=1"
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def update_scope_sync(self, scope_id: str) -> None:
        now = now_iso()
        with self.conn() as c:
            c.execute("UPDATE source_scopes SET last_synced_at=?,updated_at=? WHERE id=?", (now,now,scope_id))

    def update_source_sync(self, source_id: str, content_digest: str, revision: str = "") -> None:
        now = now_iso()
        with self.conn() as c:
            c.execute("UPDATE sources SET last_content_hash=?,last_revision=?,last_synced_at=?,updated_at=? WHERE id=?", (content_digest,revision,now,now,source_id))

    def get_target(self, tenant_id: str, user_id: str, report_type: str) -> dict[str, Any] | None:
        with self.conn() as c:
            row = c.execute("SELECT * FROM targets WHERE tenant_id=? AND user_id=? AND report_type=?", (tenant_id,user_id,report_type)).fetchone()
            return dict(row) if row else None

    def upsert_target(self, tenant_id: str, user_id: str, report_type: str, document_id: str, block_id: str, document_url: str = "") -> dict[str, Any]:
        if report_type not in {"daily", "weekly"}:
            raise ValueError("report_type 必须为 daily 或 weekly")
        now = now_iso()
        with self.conn() as c:
            old = c.execute("SELECT id FROM targets WHERE tenant_id=? AND user_id=? AND report_type=?", (tenant_id,user_id,report_type)).fetchone()
            target_id = old["id"] if old else str(uuid.uuid4())
            c.execute("""INSERT INTO targets(id,tenant_id,user_id,report_type,document_id,block_id,document_url,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id,user_id,report_type) DO UPDATE SET document_id=excluded.document_id,block_id=excluded.block_id,document_url=excluded.document_url,updated_at=excluded.updated_at""",
                (target_id,tenant_id,user_id,report_type,document_id,block_id,document_url,now,now))
            return dict(c.execute("SELECT * FROM targets WHERE id=?", (target_id,)).fetchone())


    def update_fact_classification(self, tenant_id: str, user_id: str, fact_id: str, *, business: str | None = None, project: str | None = None) -> dict[str, Any]:
        fields = {k: v for k, v in {"business": business, "project": project}.items() if v is not None}
        if not fields:
            raise ValueError("至少提供业务或项目归属")
        now = now_iso()
        sets = ",".join(f"{k}=?" for k in fields)
        with self.conn() as c:
            row = c.execute("SELECT * FROM facts WHERE tenant_id=? AND user_id=? AND id=?", (tenant_id,user_id,fact_id)).fetchone()
            if not row and len(fact_id) >= 6:
                matches = c.execute("SELECT * FROM facts WHERE tenant_id=? AND user_id=? AND id LIKE ? LIMIT 2", (tenant_id,user_id,fact_id + "%")).fetchall()
                if len(matches) == 1:
                    row = matches[0]
            if not row:
                raise ValueError("找不到当前用户范围内的事实记录")
            actual_id = row["id"]
            values = list(fields.values()) + [now, tenant_id, user_id, actual_id]
            c.execute(f"UPDATE facts SET {sets},updated_at=? WHERE tenant_id=? AND user_id=? AND id=?", values)
            updated = c.execute("SELECT * FROM facts WHERE tenant_id=? AND user_id=? AND id=?", (tenant_id,user_id,actual_id)).fetchone()
            return self._fact_row(updated)

    def upsert_project_ownership(self, tenant_id: str, user_id: str, project_name: str, *, business: str = "", owner_name: str = "", owner_user_id: str = "", role: str = "contributor", note: str = "") -> dict[str, Any]:
        project_name = project_name.strip()
        if not project_name:
            raise ValueError("项目名称不能为空")
        if role not in {"owner", "contributor", "observer"}:
            raise ValueError("role 必须为 owner、contributor 或 observer")
        now = now_iso()
        with self.conn() as c:
            old = c.execute("SELECT id FROM project_ownership WHERE tenant_id=? AND user_id=? AND project_name=?", (tenant_id,user_id,project_name)).fetchone()
            row_id = old["id"] if old else str(uuid.uuid4())
            c.execute("""INSERT INTO project_ownership(id,tenant_id,user_id,project_name,business,owner_name,owner_user_id,role,note,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id,user_id,project_name) DO UPDATE SET
                business=excluded.business,owner_name=excluded.owner_name,owner_user_id=excluded.owner_user_id,
                role=excluded.role,note=excluded.note,updated_at=excluded.updated_at""",
                (row_id,tenant_id,user_id,project_name,business,owner_name,owner_user_id,role,note,now,now))
            return dict(c.execute("SELECT * FROM project_ownership WHERE id=?", (row_id,)).fetchone())

    def list_project_ownership(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM project_ownership WHERE tenant_id=? AND user_id=? ORDER BY project_name", (tenant_id,user_id)).fetchall()]

    def supersede_pending_drafts(self, tenant_id: str, user_id: str, kind: str) -> int:
        now = now_iso()
        with self.conn() as c:
            cursor = c.execute("UPDATE drafts SET status='superseded',last_error='被用户明确要求重新生成的新草稿替代',updated_at=? WHERE tenant_id=? AND user_id=? AND kind=? AND status='pending_confirmation'", (now,tenant_id,user_id,kind))
            return cursor.rowcount

    def create_draft(self, tenant_id: str, user_id: str, kind: str, start: str, end: str, content: str,
                     base_text_hash: str = "", target_doc_id: str = "", target_block_id: str = "") -> dict[str, Any]:
        draft_id = str(uuid.uuid4())[:8]
        now = now_iso()
        with self.conn() as c:
            c.execute("INSERT INTO drafts(id,tenant_id,user_id,kind,period_start,period_end,content,status,version,base_text_hash,target_doc_id,target_block_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'pending_confirmation',1,?,?,?,?,?)",
                      (draft_id,tenant_id,user_id,kind,start,end,content,base_text_hash,target_doc_id,target_block_id,now,now))
            return dict(c.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone())

    def get_draft(self, tenant_id: str, user_id: str, draft_id: str) -> dict[str, Any] | None:
        with self.conn() as c:
            row = c.execute("SELECT * FROM drafts WHERE tenant_id=? AND user_id=? AND id=?", (tenant_id,user_id,draft_id)).fetchone()
            return dict(row) if row else None

    def list_drafts(self, tenant_id: str, user_id: str, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        sql = "SELECT * FROM drafts WHERE tenant_id=? AND user_id=?"; params: list[Any] = [tenant_id,user_id]
        if status:
            sql += " AND status=?"; params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"; params.append(limit)
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def latest_pending_draft(self, tenant_id: str, user_id: str, kind: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT * FROM drafts WHERE tenant_id=? AND user_id=? AND status='pending_confirmation'"; params: list[Any] = [tenant_id,user_id]
        if kind:
            sql += " AND kind=?"; params.append(kind)
        sql += " ORDER BY created_at DESC LIMIT 1"
        with self.conn() as c:
            row = c.execute(sql, params).fetchone()
            return dict(row) if row else None

    def update_draft_content(self, tenant_id: str, user_id: str, draft_id: str, content: str) -> dict[str, Any]:
        now = now_iso()
        with self.conn() as c:
            c.execute("UPDATE drafts SET content=?,version=version+1,updated_at=? WHERE tenant_id=? AND user_id=? AND id=? AND status='pending_confirmation'", (content,now,tenant_id,user_id,draft_id))
            row = c.execute("SELECT * FROM drafts WHERE tenant_id=? AND user_id=? AND id=?", (tenant_id,user_id,draft_id)).fetchone()
            if not row: raise ValueError("找不到草稿")
            if row["status"] != "pending_confirmation": raise ValueError("该草稿已确认，不能继续修改")
            return dict(row)

    def confirm_draft(self, tenant_id: str, user_id: str, draft_id: str) -> dict[str, Any]:
        now = now_iso()
        with self.conn() as c:
            row = c.execute("SELECT * FROM drafts WHERE tenant_id=? AND user_id=? AND id=?", (tenant_id,user_id,draft_id)).fetchone()
            if not row: raise ValueError("找不到草稿")
            if row["status"] == "published": return dict(row)
            if row["status"] != "pending_confirmation": raise ValueError(f"草稿当前状态为 {row['status']}，无法确认")
            c.execute("UPDATE drafts SET status='confirmed_pending_writeback',confirmed_at=?,updated_at=? WHERE id=?", (now,now,draft_id))
            return dict(c.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone())

    def mark_draft_result(self, draft_id: str, status: str, error: str = "") -> dict[str, Any] | None:
        now = now_iso()
        written_at = now if status == "published" else ""
        with self.conn() as c:
            c.execute("UPDATE drafts SET status=?,last_error=?,written_at=CASE WHEN ?='published' THEN ? ELSE written_at END,updated_at=? WHERE id=?", (status,error,status,written_at,now,draft_id))
            row = c.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
            return dict(row) if row else None

    def claim_message(self, message_id: str) -> bool:
        if not message_id: return True
        try:
            with self.conn() as c:
                c.execute("INSERT INTO processed_messages(message_id,received_at) VALUES(?,?)", (message_id,now_iso()))
            return True
        except sqlite3.IntegrityError:
            return False

    def mark_message_processed(self, message_id: str) -> None:
        with self.conn() as c:
            c.execute("UPDATE processed_messages SET processed_at=? WHERE message_id=?", (now_iso(),message_id))

    def audit(self, tenant_id: str, user_id: str, action: str, entity_id: str = "", details: dict[str, Any] | None = None) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO audit_log(id,tenant_id,user_id,action,entity_id,details_json,created_at) VALUES(?,?,?,?,?,?,?)",
                      (str(uuid.uuid4()),tenant_id,user_id,action,entity_id,json.dumps(details or {},ensure_ascii=False),now_iso()))

    def update_schedule_markers(self, tenant_id: str, user_id: str, daily_date: str | None = None, weekly_date: str | None = None) -> None:
        sets=[]; vals=[]
        if daily_date is not None: sets.append("last_daily_date=?"); vals.append(daily_date)
        if weekly_date is not None: sets.append("last_weekly_date=?"); vals.append(weekly_date)
        if not sets: return
        sets.append("updated_at=?"); vals.append(now_iso())
        vals.extend([tenant_id,user_id])
        with self.conn() as c:
            c.execute(f"UPDATE users SET {','.join(sets)} WHERE tenant_id=? AND user_id=?", vals)
