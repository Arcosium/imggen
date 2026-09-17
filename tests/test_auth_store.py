import pytest

from auth import store


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "USERS_PATH", str(tmp_path / "users.json"))
    monkeypatch.setattr(store, "_attempts", {})
    monkeypatch.setattr(store, "MAX_ATTEMPTS", 5)
    monkeypatch.setattr(store, "LOCKOUT_SECONDS", 900)
    return store


def test_seed_admin_idempotent(tmp_store):
    tmp_store.seed_admin()
    tmp_store.seed_admin()
    users = tmp_store._load()
    admins = [u for u in users.values() if u.get("role") == "admin"]
    assert len(admins) == 1
    assert admins[0]["status"] == "approved"
    assert admins[0]["username"] == "hh09080"


def test_seed_admin_password_verifies(tmp_store, monkeypatch):
    # 평문을 코드에 두지 않기 위해 테스트는 env ADMIN_PASSWORD 경로로 시드한다.
    monkeypatch.setenv("ADMIN_PASSWORD", "seed-test-pw-123")
    tmp_store.seed_admin()
    assert tmp_store.verify_credentials("hh09080", "seed-test-pw-123") is True
    assert tmp_store.verify_credentials("hh09080", "wrong") is False


def test_create_pending_then_approve(tmp_store):
    ok, _ = tmp_store.create_pending("alice", "pw12345")
    assert ok is True
    # pending 사용자는 로그인 불가
    assert tmp_store.verify_credentials("alice", "pw12345") is False
    assert "alice" in tmp_store.list_pending()
    assert tmp_store.approve("alice") is True
    assert tmp_store.verify_credentials("alice", "pw12345") is True
    assert "alice" not in tmp_store.list_pending()


def test_create_pending_rejects_duplicate_and_empty(tmp_store):
    assert tmp_store.create_pending("", "x")[0] is False
    assert tmp_store.create_pending("bob", "")[0] is False
    assert tmp_store.create_pending("bob", "pw12345")[0] is True
    ok, msg = tmp_store.create_pending("bob", "another")
    assert ok is False and "이미" in msg


def test_reject_blocks_login(tmp_store):
    tmp_store.create_pending("carol", "pw12345")
    tmp_store.reject("carol")
    assert tmp_store.verify_credentials("carol", "pw12345") is False
    assert "carol" not in tmp_store.list_pending()


def test_is_admin(tmp_store):
    tmp_store.seed_admin()
    tmp_store.create_pending("dave", "pw12345")
    tmp_store.approve("dave")
    assert tmp_store.is_admin("hh09080") is True
    assert tmp_store.is_admin("dave") is False
    assert tmp_store.is_admin("nobody") is False


def test_check_login_locks_after_max_attempts(tmp_store):
    tmp_store.create_pending("erin", "rightpw")
    tmp_store.approve("erin")
    for _ in range(5):
        assert tmp_store.check_login("erin", "wrong") is False
    # 잠금 상태 — 정답이어도 거부
    assert tmp_store.check_login("erin", "rightpw") is False


def test_check_login_success_resets_counter(tmp_store):
    tmp_store.create_pending("frank", "rightpw")
    tmp_store.approve("frank")
    tmp_store.check_login("frank", "wrong")
    tmp_store.check_login("frank", "wrong")
    assert tmp_store.check_login("frank", "rightpw") is True
    # 카운터 리셋되어 이후 실패가 누적 0부터
    assert "frank" not in tmp_store._attempts


def test_check_login_lock_expires(tmp_store, monkeypatch):
    tmp_store.create_pending("gina", "rightpw")
    tmp_store.approve("gina")
    clock = {"t": 1000.0}
    monkeypatch.setattr(store.time, "time", lambda: clock["t"])
    for _ in range(5):
        tmp_store.check_login("gina", "wrong")
    assert tmp_store.check_login("gina", "rightpw") is False  # 잠김
    clock["t"] += 901  # 잠금 시간 경과
    assert tmp_store.check_login("gina", "rightpw") is True


def test_verify_credentials_missing_user(tmp_store):
    assert tmp_store.verify_credentials("ghost", "whatever") is False
