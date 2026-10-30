import asyncio

from projectsync.service import ProjectSyncService
from projectsync.store import Store


def run(coro):
    return asyncio.run(coro)


def test_bot_message_record_and_generate_daily(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    service = ProjectSyncService(store=store)
    reply = run(service.handle_message("tenant", "user", "记录：完成接口联调，等待验收"))
    assert "已记录" in reply
    facts = store.list_facts("tenant", "user")
    assert len(facts) == 1
    reply = run(service.handle_message("tenant", "user", "生成日报"))
    assert "日报草稿" in reply
    drafts = store.list_drafts("tenant", "user", status="pending_confirmation")
    assert len(drafts) == 1
    assert "完成接口联调" in drafts[0]["content"]


def test_help_and_schedule_setting(tmp_path):
    service = ProjectSyncService(store=Store(tmp_path / "test.sqlite3"))
    help_reply = run(service.handle_message("tenant", "user", "帮助"))
    assert "生成日报" in help_reply
    setting_reply = run(service.handle_message("tenant", "user", "设置日报时间 19:15"))
    assert "19:15" in setting_reply
    user = service.store.get_user("tenant", "user")
    assert user["daily_time"] == "19:15"


def test_project_ownership_can_be_adjusted_in_private_scope(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    service = ProjectSyncService(store=store)
    reply = run(service.handle_message("tenant", "user-a", "设置项目归属 渠道接入 | 业务=交易渠道 | 负责人=我 | 角色=负责人"))
    assert "已更新" in reply
    rows = store.list_project_ownership("tenant", "user-a")
    assert len(rows) == 1
    assert rows[0]["project_name"] == "渠道接入"
    assert rows[0]["owner_user_id"] == "user-a"
    assert rows[0]["role"] == "owner"
    assert store.list_project_ownership("tenant", "user-b") == []


def test_fact_reclassification_changes_business_and_project_only(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    fact, _ = store.add_fact("tenant", "user-a", "完成接口联调", business="旧业务", project="旧项目")
    service = ProjectSyncService(store=store)
    reply = run(service.handle_message("tenant", "user-a", f"调整归属 {fact['id'][:8]} | 业务=交易渠道 | 项目=渠道接入"))
    assert "已调整" in reply
    updated = store.list_facts("tenant", "user-a")[0]
    assert updated["content"] == "完成接口联调"
    assert updated["business"] == "交易渠道"
    assert updated["project"] == "渠道接入"


def test_ambiguous_edit_with_daily_and_weekly_drafts_asks_user(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    store.create_draft("tenant", "user-a", "daily", "2026-10-29", "2026-10-29", "日报内容")
    store.create_draft("tenant", "user-a", "weekly", "2026-10-26", "2026-11-01", "周报内容")
    service = ProjectSyncService(store=store)
    reply = run(service.handle_message("tenant", "user-a", "把第二条改成已完成"))
    assert "请说明要修改哪一份" in reply
    assert len(store.list_drafts("tenant", "user-a", status="pending_confirmation")) == 2
