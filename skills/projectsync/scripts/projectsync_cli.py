#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

try:
    from projectsync.store import Store
    from projectsync.core import local_draft, period_for, today_in
except Exception as exc:
    print("无法导入 ProjectSync AI 核心包。请在项目根目录执行 pip install -e .。", file=sys.stderr)
    raise

DEFAULT_DB = Path.home() / ".projectsync" / "projectsync.sqlite3"
DEFAULT_TENANT = "local"
DEFAULT_USER = os.getenv("PROJECTSYNC_LOCAL_USER", "local-user")


def read_content(args) -> str:
    if getattr(args, "content_file", None):
        return Path(args.content_file).read_text(encoding="utf-8")
    return getattr(args, "content", "") or ""


def main() -> int:
    parser = argparse.ArgumentParser(description="ProjectSync AI local work-fact and draft store")
    parser.add_argument("--db", default=str(DEFAULT_DB), help=f"SQLite path (default: {DEFAULT_DB})")
    parser.add_argument("--tenant", default=DEFAULT_TENANT)
    parser.add_argument("--user", default=DEFAULT_USER)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize local private database")
    add = sub.add_parser("add-fact", help="Store one work fact")
    add.add_argument("--content", required=True)
    add.add_argument("--date", default=date.today().isoformat())
    add.add_argument("--business", default="")
    add.add_argument("--project", default="")
    add.add_argument("--contribution", choices=["completed", "coordinated", "followed_up", "background"], default="completed")
    add.add_argument("--source-url", default="")
    add.add_argument("--source-excerpt", default="")
    add.add_argument("--confidence", type=float, default=0.7)

    listing = sub.add_parser("list-facts", help="List work facts")
    listing.add_argument("--since", default=None)
    listing.add_argument("--until", default=None)
    listing.add_argument("--limit", type=int, default=100)

    update_fact = sub.add_parser("update-fact", help="Change business/project classification of one of your facts")
    update_fact.add_argument("--id", required=True)
    update_fact.add_argument("--business", default=None)
    update_fact.add_argument("--project", default=None)

    set_owner = sub.add_parser("set-project-ownership", help="Set a project mapping in the current user's private scope")
    set_owner.add_argument("--project", required=True)
    set_owner.add_argument("--business", default="")
    set_owner.add_argument("--owner-name", default="")
    set_owner.add_argument("--owner-user-id", default="")
    set_owner.add_argument("--role", choices=["owner", "contributor", "observer"], default="contributor")
    set_owner.add_argument("--note", default="")

    sub.add_parser("list-project-ownerships", help="List project mappings for the current user")

    export = sub.add_parser("export-context", help="Export facts as JSON for the host agent")
    export.add_argument("--since", default=None)
    export.add_argument("--until", default=None)

    draft = sub.add_parser("make-draft", help="Save a pending report draft")
    draft.add_argument("--kind", choices=["daily", "weekly"], required=True)
    draft.add_argument("--start", default=None)
    draft.add_argument("--end", default=None)
    draft.add_argument("--content", default="")
    draft.add_argument("--content-file", default=None)

    drafts = sub.add_parser("list-drafts", help="List report drafts")
    drafts.add_argument("--status", default=None)

    show = sub.add_parser("show-draft", help="Show a draft")
    show.add_argument("--id", required=True)

    edit = sub.add_parser("edit-draft", help="Replace a draft with revised content")
    edit.add_argument("--id", required=True)
    edit.add_argument("--content", default="")
    edit.add_argument("--content-file", default=None)

    confirm = sub.add_parser("confirm-draft", help="Record explicit confirmation; this does not publish")
    confirm.add_argument("--id", required=True)

    args = parser.parse_args()
    store = Store(args.db)
    store.ensure_user(args.tenant, args.user)

    if args.command == "init":
        print(json.dumps({"ok": True, "database": str(Path(args.db).expanduser())}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "add-fact":
        fact, created = store.add_fact(args.tenant, args.user, args.content, occurred_at=args.date, business=args.business,
                                       project=args.project, contribution=args.contribution, confidence=args.confidence,
                                       source_url=args.source_url, source_excerpt=args.source_excerpt)
        print(json.dumps({"created": created, "fact": fact}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "list-facts":
        print(json.dumps(store.list_facts(args.tenant, args.user, args.since, args.until, args.limit), ensure_ascii=False, indent=2))
        return 0
    if args.command == "update-fact":
        result = store.update_fact_classification(args.tenant, args.user, args.id, business=args.business, project=args.project)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "set-project-ownership":
        result = store.upsert_project_ownership(args.tenant, args.user, args.project, business=args.business, owner_name=args.owner_name,
                                                owner_user_id=args.owner_user_id, role=args.role, note=args.note)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "list-project-ownerships":
        print(json.dumps(store.list_project_ownership(args.tenant, args.user), ensure_ascii=False, indent=2))
        return 0
    if args.command == "export-context":
        print(json.dumps({"tenant_id": args.tenant, "user_id": args.user, "facts": store.list_facts(args.tenant, args.user, args.since, args.until, 500)}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "make-draft":
        today = today_in()
        start, end = period_for(args.kind, today)
        start = date.fromisoformat(args.start) if args.start else start
        end = date.fromisoformat(args.end) if args.end else end
        content = read_content(args)
        if not content:
            facts = store.list_facts(args.tenant, args.user, start.isoformat(), end.isoformat(), 200)
            content = local_draft(args.kind, facts, start, end)
        result = store.create_draft(args.tenant, args.user, args.kind, start.isoformat(), end.isoformat(), content)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "list-drafts":
        print(json.dumps(store.list_drafts(args.tenant, args.user, args.status), ensure_ascii=False, indent=2))
        return 0
    if args.command == "show-draft":
        result = store.get_draft(args.tenant, args.user, args.id)
        if not result:
            print("Draft not found", file=sys.stderr); return 2
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    if args.command == "edit-draft":
        content = read_content(args)
        if not content:
            print("Provide --content or --content-file", file=sys.stderr); return 2
        result = store.update_draft_content(args.tenant, args.user, args.id, content)
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    if args.command == "confirm-draft":
        result = store.confirm_draft(args.tenant, args.user, args.id)
        print(json.dumps({"confirmed": True, "published": False, "note": "Confirmation is recorded locally; online writeback must be performed by a separately authorized host tool after re-reading the target.", "draft": result}, ensure_ascii=False, indent=2))
        return 0
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
