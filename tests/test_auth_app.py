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
