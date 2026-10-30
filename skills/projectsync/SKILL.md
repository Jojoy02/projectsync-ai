---
name: projectsync
description: Track the current user's work facts across authorized online documents, meeting notes and calendar context; associate facts with business areas and projects; prepare daily/weekly report drafts; revise drafts in natural language; and write back only after explicit confirmation when the host provides an authorized document-editing tool.
---

# ProjectSync AI — Agent Skill

Use this skill when the user wants to record work progress, review projects, connect information across work documents, prepare a daily/weekly report, or safely update an existing report document.

## Operating rules

- Treat the current user as the ownership boundary. Do not build or retain another teammate's personal project history merely because it appears in a shared document.
- Read only sources the user or host agent is authorized to access. A URL is not proof of access permission.
- Prefer existing online documents, meeting minutes, calendar details and explicit user notes over asking the user to re-enter information.
- First identify what the current user actually did; then classify each fact by business/product and project. One fact may link to both views but must be stored and counted once.
- Distinguish `completed`, `coordinated`, `followed_up`, and `background`. A meeting invite or planned task is not evidence that the work happened or was completed.
- Preserve evidence: source URL, title, relevant excerpt, date and confidence. If a material relationship or completion status is uncertain, leave it marked for review rather than asking the user to approve every high-confidence association.
- Generate drafts in the format and structure of the user's existing report document. A weekly report is a synthesis, not a concatenation of daily reports.
- Daily and weekly drafts are separate objects. If both are ready on the same day, show them in one message but ask for independent confirmation.
- Never publish, overwrite, or edit an online document before the user explicitly confirms the specific draft. When writing back, re-read the target immediately before editing and change only the mapped paragraph/section owned by the user. Stop if the target moved or changed.
- Never claim a document was updated unless the host tool reports success.
- If the host has no persistent storage, do not claim cross-session memory. If no scheduler is available, do not claim proactive scheduled delivery.

## Workflow

### 1. Gather evidence with available tools

Use the connected document/MCP tools to search authorized folders or inspect links supplied by the user. Where available, inspect:

- project plans and milestone documents;
- daily progress notes and existing daily/weekly reports;
- meeting minutes or transcript summaries;
- calendar events as context only;
- explicit work updates supplied in the current conversation.

Do not use calendar events alone to infer decisions or completion. A meeting's outcome needs minutes, a follow-up record, or user confirmation.

### 2. Extract facts before writing a report

For each candidate fact, record:

- date;
- concise factual description;
- business/product area (if known);
- project (if known);
- the user's contribution type;
- source URL and a short evidence excerpt;
- confidence and review status.

Link facts to a business and a project when the relationship is clear. If it is uncertain but does not affect the requested output, keep the fact unlinked for now. Ask only when the ambiguity changes ownership, project status, or the target section to update.

### 3. Persist local facts and drafts when the repository is installed

Use the local CLI in `scripts/projectsync_cli.py`. Install the repository with `pip install -e .` first. By default, it stores data under `~/.projectsync/projectsync.sqlite3`, outside the public repository.

Examples:

```bash
python skills/projectsync/scripts/projectsync_cli.py init
python skills/projectsync/scripts/projectsync_cli.py add-fact --content "完成接口联调，等待业务验收" --business "交易渠道" --project "渠道接入" --contribution completed --date 2026-10-29 --source-url "https://example.feishu.cn/docx/REDACTED"
python skills/projectsync/scripts/projectsync_cli.py list-facts --since 2026-10-27 --until 2026-10-29
python skills/projectsync/scripts/projectsync_cli.py export-context
```

If the CLI is unavailable, keep the facts in the current session and be explicit that they were not persisted.

### Correct a business/project association or ownership

Users can reclassify one of their own fact records without changing the original work description:

```bash
python skills/projectsync/scripts/projectsync_cli.py list-facts
python skills/projectsync/scripts/projectsync_cli.py update-fact --id FACT_ID --business "交易渠道" --project "渠道接入"
```

Project responsibility metadata is separately editable in the current user's private scope:

```bash
python skills/projectsync/scripts/projectsync_cli.py set-project-ownership --project "渠道接入" --business "交易渠道" --owner-name "当前用户" --owner-user-id "local-user" --role owner
python skills/projectsync/scripts/projectsync_cli.py list-project-ownerships
```

Changing project ownership metadata does not transfer or reveal another teammate's personal work facts. Ask for clarification only if the reassignment changes who owns the output or where the confirmed report must be written.

### 4. Prepare a draft

For a daily report, focus on today's evidenced work, results, blockers and next steps. For a weekly report, summarize stage results, meaningful changes, unresolved commitments and next week's actions by business/project. Remove duplicates across sources and do not inflate team results into personal achievements.

Use `make-draft` to store the exact draft the user will review:

```bash
python skills/projectsync/scripts/projectsync_cli.py make-draft --kind daily --start 2026-10-29 --end 2026-10-29 --content-file /path/to/draft.txt
```

Show the complete draft in the host conversation or supported message surface. Keep uncertain items visibly marked.

### 5. Revise naturally

When the user asks to edit a draft, revise only the requested part and show the complete revised draft. Preserve unrelated content. A request to remove a line from the report does not mean deleting the underlying work fact.

Update the saved draft with:

```bash
python skills/projectsync/scripts/projectsync_cli.py edit-draft --id DRAFT_ID --content-file /path/to/revised-draft.txt
```

### 6. Confirm and write back

A clear confirmation such as “确认日报” or “确认周报” applies only to the named draft. If both exist, ask which one is being confirmed. Record confirmation locally:

```bash
python skills/projectsync/scripts/projectsync_cli.py confirm-draft --id DRAFT_ID
```

This command records confirmation; it does **not** write to an online document. After confirmation, if the host has a document-editing tool:

1. re-read the mapped target document and the user's target section;
2. verify the target is still the same version/content reviewed;
3. update only the explicitly mapped user-owned paragraph/section;
4. verify the result;
5. report success only if the host tool confirms it.

If the host lacks an editing tool, say the draft is confirmed locally but not published, and provide the target text for the user to paste.

## Quick commands to interpret

- “记录：……” — capture a work fact.
- “添加文档 <URL>” — inspect the URL if an authorized document tool is available.
- “生成日报” / “生成周报” — prepare the corresponding draft.
- “我最近跟进哪些项目？” — answer from the user's saved facts and re-check recent sources where possible.
- “最近记录” / “调整归属 <记录ID> | 业务=... | 项目=...” — show facts and correct a specific fact's business/project classification.
- “设置项目归属 <项目名> | 业务=... | 负责人=我 | 角色=负责人” — update the current user's project mapping; do not move another user's facts.
- “把……改成……” / “补充……” — revise the current draft when one is pending; otherwise update the work record only if the user clearly means a factual correction.
- “确认日报” / “确认周报” — confirm only the named draft, then use a supported write tool if available.
