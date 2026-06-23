import pytest

from auth import store
import app


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "USERS_PATH", str(tmp_path / "users.json"))
    monkeypatch.setattr(store, "_attempts", {})
    monkeypatch.setattr(store, "MAX_ATTEMPTS", 5)
    return store


def test_authenticate_only_approved(tmp_store):
    tmp_store.create_pending("alice", "pw12345")
    assert app.authenticate("alice", "pw12345") is False   # pending
    tmp_store.approve("alice")
    assert app.authenticate("alice", "pw12345") is True
    assert app.authenticate("alice", "nope") is False


def test_signup_submit_creates_pending(tmp_store):
    ok, msg = app.signup_submit("bob", "pw12345")
    assert ok is True
    assert "bob" in tmp_store.list_pending()
    ok2, msg2 = app.signup_submit("bob", "pw12345")
    assert ok2 is False and "이미" in msg2


def test_signup_page_html_has_form_no_model_names():
    html = app._signup_page_html()
    assert "<form" in html and 'action="signup"' in html.replace("'", '"')
    for w in ["FLUX", "Qwen", "Veo", "Gemini", "Imagen", "ComfyUI", "Wan"]:
        assert w not in html


def test_admin_view_requires_admin(tmp_store):
    tmp_store.seed_admin()
    tmp_store.create_pending("hank", "pw12345")
    allowed, pending, msg = app._admin_view("hh09080")
    assert allowed is True and "hank" in pending
    allowed2, pending2, msg2 = app._admin_view("hank")
    assert allowed2 is False and pending2 == [] and "관리자" in msg2


def test_admin_approve_action_gated(tmp_store):
    tmp_store.seed_admin()
    tmp_store.create_pending("ivy", "pw12345")
    # 비관리자는 승인 불가
    ok, msg = app.admin_approve_action("ivy", "ivy")
    assert ok is False and "관리자" in msg
    assert tmp_store.verify_credentials("ivy", "pw12345") is False
    # 관리자는 승인 가능
    ok2, msg2 = app.admin_approve_action("ivy", "hh09080")
    assert ok2 is True
    assert tmp_store.verify_credentials("ivy", "pw12345") is True


def test_admin_reject_action_gated(tmp_store):
    tmp_store.seed_admin()
    tmp_store.create_pending("jack", "pw12345")
    ok, _ = app.admin_reject_action("jack", "hh09080")
    assert ok is True
    assert "jack" not in tmp_store.list_pending()
    assert tmp_store.verify_credentials("jack", "pw12345") is False


def test_render_manual_html_returns_string():
    html = app.render_manual_html()
    assert isinstance(html, str) and len(html) > 0
