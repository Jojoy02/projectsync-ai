from datetime import date

from projectsync.core import content_hash, local_draft, parse_docx_url, parse_folder_url, period_for, text_hash
from projectsync.store import Store


def test_fact_dedup_and_user_isolation(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    store.ensure_user("tenant-a", "user-a")
    store.ensure_user("tenant-a", "user-b")
    first, created = store.add_fact("tenant-a", "user-a", "完成接口联调", occurred_at="2026-10-29", project="渠道接入")
    assert created is True
    duplicate, created = store.add_fact("tenant-a", "user-a", " 完成接口联调 ", occurred_at="2026-10-29", project="渠道接入")
    assert created is False
    assert duplicate["id"] == first["id"]
    other_user, created = store.add_fact("tenant-a", "user-b", "完成接口联调", occurred_at="2026-10-29")
    assert created is True
    assert other_user["id"] != first["id"]
    recurring, created = store.add_fact("tenant-a", "user-a", "完成接口联调", occurred_at="2026-10-30", project="渠道接入")
    assert created is True
    assert recurring["id"] != first["id"]
    assert len(store.list_facts("tenant-a", "user-a")) == 2
    assert len(store.list_facts("tenant-a", "user-b")) == 1


def test_business_project_dual_association_is_one_fact(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    store.add_fact("t", "u", "确认验收口径", business="交易渠道", project="支付体验优化")
    facts = store.list_facts("t", "u")
    assert len(facts) == 1
    assert facts[0]["business"] == "交易渠道"
    assert facts[0]["project"] == "支付体验优化"


def test_draft_confirm_does_not_publish(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    draft = store.create_draft("t", "u", "daily", "2026-10-29", "2026-10-29", "日报内容")
    assert draft["status"] == "pending_confirmation"
    confirmed = store.confirm_draft("t", "u", draft["id"])
    assert confirmed["status"] == "confirmed_pending_writeback"
    assert confirmed["written_at"] == ""


def test_draft_cannot_be_edited_after_confirmation(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    draft = store.create_draft("t", "u", "weekly", "2026-10-26", "2026-11-01", "周报")
    store.confirm_draft("t", "u", draft["id"])
    try:
        store.update_draft_content("t", "u", draft["id"], "修改后的周报")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "已确认" in str(exc)


def test_docx_url_validation():
    assert parse_docx_url("https://acme.feishu.cn/docx/Abc_123?from=copy") == "Abc_123"
    for url in ["http://acme.feishu.cn/docx/token", "https://evil.example/docx/token", "https://acme.feishu.cn/wiki/token"]:
        try:
            parse_docx_url(url)
            assert False, f"expected rejection: {url}"
        except ValueError:
            pass


def test_period_and_local_draft():
    start, end = period_for("weekly", date(2026, 10, 29))
    assert start.isoformat() == "2026-10-26"
    assert end.isoformat() == "2026-11-01"
    draft = local_draft("daily", [{"content": "完成接口联调", "business": "交易渠道", "project": "渠道接入", "contribution": "completed"}], date(2026, 10, 29), date(2026, 10, 29))
    assert "交易渠道" in draft
    assert "完成接口联调" in draft


def test_hash_helpers_are_stable():
    assert content_hash("完成联调") == content_hash(" 完成联调 ")
    assert text_hash("a") != text_hash("b")


def test_folder_url_validation():
    assert parse_folder_url("https://acme.feishu.cn/drive/folder/fldcn123") == "fldcn123"
    assert parse_folder_url("https://acme.feishu.cn/drive/home?folder_token=fldcn456") == "fldcn456"
    try:
        parse_folder_url("https://evil.example/drive/folder/token")
        assert False, "expected rejection"
    except ValueError:
        pass


def test_source_scope_is_user_scoped(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    scope = store.add_source_scope("tenant", "user-a", "https://acme.feishu.cn/drive/folder/fldcn123", "fldcn123")
    assert scope["folder_token"] == "fldcn123"
    assert len(store.list_source_scopes("tenant", "user-a")) == 1
    assert store.list_source_scopes("tenant", "user-b") == []
