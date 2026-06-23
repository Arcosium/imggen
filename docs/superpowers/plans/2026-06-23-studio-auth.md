# Studio 접근 인증 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** image_generator 스튜디오를 로그인 게이트 + admin 승인제 가입으로 보호하고, 시드 admin(hh09080)·아이디당 5회 로그인 제한을 추가한다.

**Architecture:** stdlib `hashlib` pbkdf2 기반 JSON 사용자 저장소(`auth/store.py`, Gradio 비의존)를 만들고, Gradio 내장 `auth=` 콜백으로 스튜디오를 게이트한다. 가입은 게이트 밖 공개 FastAPI `/signup` 라우트, 승인은 게이트된 Gradio "관리자" 탭, 사용설명서는 게이트된 Gradio 탭으로 이동한다. 핸들러 로직은 모듈 레벨 순수 함수로 분리해 테스트한다.

**Tech Stack:** Python 3, Gradio 4.44.1(`mount_gradio_app(auth=...)`), FastAPI(Form/HTMLResponse), stdlib hashlib/hmac/secrets/threading, pytest.

## Global Constraints

- **모델명 비노출**: 인증 UI/문구(로그인 메시지, 가입 폼, 관리자 탭, 설명서)에도 FLUX·Qwen·Wan·Veo·Gemini·Imagen·ComfyUI 등 모델/엔진명 금지.
- **신규 외부 의존 금지**: 해싱/세션은 stdlib만(`hashlib`,`hmac`,`secrets`). Gradio 내장 인증 사용. `requests` 등 추가 금지.
- **평문 비밀번호 비커밋**: 시드 admin은 사전 계산한 salt+hash만 임베드. 평문은 코드/스펙/플랜/테스트 어디에도 기록하지 않는다.
- **비밀번호 해싱**: `hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200000)`, 검증은 `hmac.compare_digest`.
- **로그인 제한**: 아이디당 연속 `LOGIN_MAX_ATTEMPTS`(기본 5)회 실패 시 `LOGIN_LOCKOUT_SECONDS`(기본 900) 잠금.
- **NSFW/기타 기존 제약 유지**.
- **테스트 실행**: `cd /home/opc/projects/image_generator && python3 -m pytest`. store 테스트는 gradio 비의존.
- **커밋 메시지 말미**: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task 1: `auth/store.py` (사용자 저장소 + 해싱 + 시드 admin + 로그인 제한)

**Files:**
- Create: `auth/__init__.py`
- Create: `auth/store.py`
- Create: `tests/test_auth_store.py`

**Interfaces:**
- Produces:
  - `USERS_PATH: str`, `ITERATIONS: int`, `BOOTSTRAP_ADMIN: dict`, `MAX_ATTEMPTS: int`, `LOCKOUT_SECONDS: int`, `_attempts: dict`
  - `seed_admin() -> None`
  - `verify_credentials(username: str, password: str) -> bool`
  - `create_pending(username: str, password: str) -> tuple[bool, str]`
  - `list_pending() -> list[str]`
  - `approve(username: str) -> bool`
  - `reject(username: str) -> bool`
  - `is_admin(username: str) -> bool`
  - `check_login(username: str, password: str) -> bool`  # 레이트리밋 포함 로그인 게이트

- [ ] **Step 1: 패키지 init 생성**

Create `auth/__init__.py`:
```python
"""스튜디오 접근 인증(사용자 저장소·로그인·가입 승인). Gradio 비의존 store."""
```

- [ ] **Step 2: 실패하는 테스트 작성**

Create `tests/test_auth_store.py`:
```python
import importlib

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
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_auth_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auth.store'`

- [ ] **Step 4: `auth/store.py` 구현**

Create `auth/store.py`:
```python
"""사용자 저장소 + pbkdf2 해싱 + 시드 admin + 로그인 시도 제한. Gradio 비의존.

저장: data/users.json. 비밀번호는 평문 저장 금지 — salt+pbkdf2 해시만.
시드 admin(hh09080)은 사전 계산한 salt+hash를 임베드(평문 비커밋); env ADMIN_PASSWORD로 교체 가능.
로그인 제한은 인메모리(_attempts) — 영속화 불필요.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USERS_PATH = os.path.join(_BASE, "data", "users.json")
ITERATIONS = 200_000

# 평문 아님 — "hh07290729!" 의 pbkdf2-sha256(200k) salt+hash (소유자 제공, 사전 계산).
BOOTSTRAP_ADMIN = {
    "username": "hh09080",
    "salt": "578ed3cb3f260ab3be1d5d69ce826655",
    "hash": "b576eab41a6b5aa9a6909418424d98bf728ca60654aacde50a50734cbe352ac7",
    "role": "admin",
    "status": "approved",
}

MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS") or "5")
LOCKOUT_SECONDS = int(os.environ.get("LOGIN_LOCKOUT_SECONDS") or "900")

_lock = threading.Lock()
_attempts = {}  # username -> {"count": int, "locked_until": float}


def _hash(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", (password or "").encode(), bytes.fromhex(salt_hex), ITERATIONS).hex()


def _load():
    if not os.path.exists(USERS_PATH):
        return {}
    try:
        with open(USERS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(users):
    os.makedirs(os.path.dirname(USERS_PATH), exist_ok=True)
    tmp = USERS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    os.replace(tmp, USERS_PATH)


def seed_admin():
    """admin 부재 시 시드 admin 생성(멱등). env ADMIN_PASSWORD 있으면 그 값으로 해시."""
    with _lock:
        users = _load()
        if any(u.get("role") == "admin" for u in users.values()):
            return
        pw = os.environ.get("ADMIN_PASSWORD")
        if pw:
            salt = secrets.token_hex(16)
            rec = {"username": BOOTSTRAP_ADMIN["username"], "salt": salt, "hash": _hash(pw, salt),
                   "role": "admin", "status": "approved", "created": int(time.time())}
        else:
            rec = dict(BOOTSTRAP_ADMIN)
            rec["created"] = int(time.time())
        users[rec["username"]] = rec
        _save(users)


def verify_credentials(username, password):
    u = _load().get(username or "")
    if not u or u.get("status") != "approved":
        return False
    return hmac.compare_digest(u.get("hash", ""), _hash(password, u.get("salt", "")))


def create_pending(username, password):
    username = (username or "").strip()
    if not username or not password:
        return False, "아이디와 비밀번호를 입력하세요."
    with _lock:
        users = _load()
        if username in users:
            return False, "이미 존재하는 아이디입니다."
        salt = secrets.token_hex(16)
        users[username] = {"username": username, "salt": salt, "hash": _hash(password, salt),
                           "role": "user", "status": "pending", "created": int(time.time())}
        _save(users)
    return True, "가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다."


def list_pending():
    return sorted(u for u, rec in _load().items() if rec.get("status") == "pending")


def _set_status(username, status):
    with _lock:
        users = _load()
        if username not in users:
            return False
        users[username]["status"] = status
        _save(users)
    return True


def approve(username):
    return _set_status(username, "approved")


def reject(username):
    return _set_status(username, "rejected")


def is_admin(username):
    u = _load().get(username or "")
    return bool(u and u.get("role") == "admin" and u.get("status") == "approved")


def check_login(username, password):
    """로그인 게이트(레이트리밋). MAX_ATTEMPTS 연속 실패 시 LOCKOUT_SECONDS 잠금. 성공 시 리셋."""
    now = time.time()
    with _lock:
        st = _attempts.get(username)
        if st and st.get("locked_until", 0) > now:
            return False
    ok = verify_credentials(username, password)
    with _lock:
        if ok:
            _attempts.pop(username, None)
            return True
        st = _attempts.get(username) or {"count": 0, "locked_until": 0}
        st["count"] += 1
        if st["count"] >= MAX_ATTEMPTS:
            st["locked_until"] = now + LOCKOUT_SECONDS
            st["count"] = 0
        _attempts[username] = st
    return False
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_auth_store.py -v`
Expected: PASS (9 passed)

- [ ] **Step 6: 전체 회귀**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest -q`
Expected: 기존 30 + 신규 9 = 39 passed (third-party 경고 외 pristine)

- [ ] **Step 7: 커밋**

```bash
cd /home/opc/projects/image_generator
git add auth/__init__.py auth/store.py tests/test_auth_store.py
git commit -m "feat(auth): pbkdf2 사용자 저장소 + 시드 admin + 로그인 5회 제한

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 로그인 게이트 + 공개 가입(`/signup`) 와이어링

**Files:**
- Modify: `app.py` (모듈 레벨에 인증 함수/상수 추가; `__main__`에서 seed + mount auth= + /signup 라우트)
- Modify: `.gitignore` (data/ 추가)
- Create: `tests/test_auth_app.py`

**Interfaces:**
- Consumes: `auth.store` (Task 1) — `check_login`, `create_pending`, `seed_admin`.
- Produces (app.py 모듈 레벨):
  - `authenticate(username: str, password: str) -> bool`
  - `signup_submit(username: str, password: str) -> tuple[bool, str]`
  - `AUTH_MESSAGE: str`
  - `_signup_page_html() -> str`, `_signup_result_html(ok: bool, msg: str) -> str`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_auth_app.py`:
```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_auth_app.py -v`
Expected: FAIL — `AttributeError: module 'app' has no attribute 'authenticate'`

- [ ] **Step 3: app.py 모듈 레벨에 인증 함수 추가**

In `app.py`, after the line `from media import backend, pipeline` (and the other top imports), add the store import:
```python
from auth import store
```

Then add these module-level definitions (place them right after the `_friendly_error` function, before `generate_image`):
```python
# =============== [ 인증: 로그인 / 가입 ] ===============
AUTH_MESSAGE = ('승인된 계정만 입장할 수 있습니다. 계정이 없다면 '
                '<a href="signup" style="color:#7ec8ff">가입 신청</a> 후 관리자 승인을 기다려 주세요.')


def authenticate(username, password):
    """Gradio 로그인 콜백 — 승인된 계정만 통과, 5회 실패 시 잠금."""
    return store.check_login(username, password)


def signup_submit(username, password):
    """가입 신청 처리(테스트 가능 순수 로직). (ok, msg) 반환."""
    return store.create_pending(username, password)


def _signup_page_html():
    return """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>가입 신청</title>
<style>
 body{background:#121212;color:#eee;font-family:'Pretendard','Apple SD Gothic Neo',sans-serif;
      display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0;}
 .card{background:#1e1e1e;border:1px solid #333;border-radius:14px;padding:32px;width:320px;}
 h1{font-size:1.3rem;margin:0 0 6px;} p{color:#aaa;font-size:.9rem;margin:0 0 18px;}
 label{display:block;font-size:.85rem;margin:12px 0 4px;}
 input{width:100%;box-sizing:border-box;padding:10px;border-radius:8px;border:1px solid #444;
       background:#2a2a2a;color:#fff;}
 button{margin-top:18px;width:100%;padding:11px;border:0;border-radius:8px;background:#ffd966;
        color:#000;font-weight:700;cursor:pointer;}
 a{color:#7ec8ff;}
</style></head><body>
<form class="card" method="post" action="signup">
 <h1>가입 신청</h1>
 <p>관리자 승인 후 로그인할 수 있습니다.</p>
 <label>아이디</label><input name="username" autocomplete="username" required>
 <label>비밀번호</label><input name="password" type="password" autocomplete="new-password" required>
 <button type="submit">가입 신청</button>
 <p style="margin-top:16px"><a href="./">← 로그인으로</a></p>
</form></body></html>"""


def _signup_result_html(ok, msg):
    color = "#8fe388" if ok else "#ff8f8f"
    return ("""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<title>가입 신청</title><style>
 body{background:#121212;color:#eee;font-family:'Pretendard',sans-serif;display:flex;min-height:100vh;
      align-items:center;justify-content:center;margin:0;}
 .card{background:#1e1e1e;border:1px solid #333;border-radius:14px;padding:32px;width:320px;text-align:center;}
 a{color:#7ec8ff;}
</style></head><body><div class="card">
 <p style="color:%s;font-size:1rem">%s</p>
 <p><a href="./">로그인으로</a> · <a href="signup">다시 신청</a></p>
</div></body></html>""" % (color, msg))
```

- [ ] **Step 4: `__main__`에서 seed + mount auth= + /signup 라우트 추가**

In `app.py`'s `__main__` block:

(a) Add `Form` to the fastapi imports. Change the existing line:
```python
    from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
```
to also import Form (add this line right after it):
```python
    from fastapi import Form
```

(b) Right after `PORT = _resolve_port()` and the `@app_api.post("/shutdown")` block, add the seed call and signup routes (place before the manual routes):
```python
    store.seed_admin()

    @app_api.get("/signup", response_class=HTMLResponse)
    def signup_page():
        return HTMLResponse(_signup_page_html())

    @app_api.post("/signup", response_class=HTMLResponse)
    def signup_post(username: str = Form(""), password: str = Form("")):
        ok, msg = signup_submit(username, password)
        return HTMLResponse(_signup_result_html(ok, msg))
```

(c) Change the mount line:
```python
    app_api = gr.mount_gradio_app(app_api, demo, path="/", root_path=root_path)
```
to:
```python
    app_api = gr.mount_gradio_app(app_api, demo, path="/", root_path=root_path,
                                  auth=authenticate, auth_message=AUTH_MESSAGE)
```

- [ ] **Step 5: `.gitignore`에 data/ 추가**

Add a line under the "# 보안" section of `.gitignore` (so the user store with password hashes is never committed):
```
# 사용자 계정 저장소(비밀번호 해시)
data/
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_auth_app.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: import/구문 확인 + 회귀**

Run: `cd /home/opc/projects/image_generator && python3 -c "import ast; ast.parse(open('app.py').read()); print('OK')"`
Expected: `OK`

Run: `cd /home/opc/projects/image_generator && python3 -m pytest -q`
Expected: 42 passed (39 + 3)

- [ ] **Step 8: 커밋**

```bash
cd /home/opc/projects/image_generator
git add app.py .gitignore tests/test_auth_app.py
git commit -m "feat(auth): Gradio 로그인 게이트 + 공개 가입(/signup) + 시드

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 관리자 승인 탭 + 사용설명서 게이트 탭

**Files:**
- Modify: `app.py` (모듈 레벨 admin 액션 함수 + manual 렌더 모듈화; build_ui에 관리자/설명서 탭; 헤더 버튼·`/manual` 라우트 제거)
- Modify: `tests/test_auth_app.py` (admin 액션 테스트 추가)

**Interfaces:**
- Consumes: `auth.store` — `is_admin`, `list_pending`, `approve`, `reject`.
- Produces (app.py 모듈 레벨):
  - `MANUAL_DOCX: str`, `render_manual_html() -> str`
  - `_admin_view(actor: str) -> tuple[bool, list[str], str]`
  - `admin_approve_action(username: str, actor: str) -> tuple[bool, str]`
  - `admin_reject_action(username: str, actor: str) -> tuple[bool, str]`

- [ ] **Step 1: admin 액션 테스트 추가**

Append to `tests/test_auth_app.py`:
```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_auth_app.py -v`
Expected: FAIL — `AttributeError: module 'app' has no attribute '_admin_view'`

- [ ] **Step 3: 모듈 레벨 admin 액션 + manual 렌더 추가**

In `app.py`, add these module-level functions (after the signup functions from Task 2, before `generate_image`):
```python
def _admin_view(actor):
    """(allowed, pending, msg) — actor가 관리자일 때만 대기 목록 노출."""
    if not store.is_admin(actor):
        return False, [], "관리자만 사용할 수 있습니다."
    pending = store.list_pending()
    return True, pending, ("대기 중 %d명" % len(pending)) if pending else "대기 중인 신청이 없습니다."


def admin_approve_action(username, actor):
    if not store.is_admin(actor):
        return False, "관리자만 사용할 수 있습니다."
    if not username:
        return False, "승인할 아이디를 선택하세요."
    store.approve(username)
    return True, "승인 완료: %s" % username


def admin_reject_action(username, actor):
    if not store.is_admin(actor):
        return False, "관리자만 사용할 수 있습니다."
    if not username:
        return False, "거절할 아이디를 선택하세요."
    store.reject(username)
    return True, "거절 완료: %s" % username
```

Also add module-level manual rendering (place near BASE_DIR/OUTPUT_DIR constants, after `_save_bytes`):
```python
MANUAL_DOCX = os.path.join(BASE_DIR, "사용설명서.docx")
_manual_cache = {"html": None}


def render_manual_html():
    """사용설명서 .docx 를 HTML 본문 조각으로 변환(탭 내 gr.HTML 용). 캐시."""
    if _manual_cache["html"] is not None:
        return _manual_cache["html"]
    if not os.path.exists(MANUAL_DOCX):
        html = "<p>사용설명서 파일을 찾을 수 없습니다.</p>"
    else:
        try:
            import mammoth
            with open(MANUAL_DOCX, "rb") as f:
                html = mammoth.convert_to_html(f).value
        except Exception:
            try:
                from docx import Document
                doc = Document(MANUAL_DOCX)
                html = "".join(
                    "<p>%s</p>" % (p.text or "").replace("<", "&lt;").replace(">", "&gt;")
                    for p in doc.paragraphs)
            except Exception as e2:
                html = "<pre>사용설명서 변환 실패: %s</pre>" % e2
    _manual_cache["html"] = "<div style='max-width:880px;line-height:1.7'>%s</div>" % html
    return _manual_cache["html"]
```

- [ ] **Step 4: build_ui — 헤더 버튼 제거 + 관리자/설명서 탭 추가**

In `build_ui()`, remove the header manual button. Change:
```python
            with gr.Column(scale=1, min_width=140):
                gr.Button("📖 사용설명서", link="manual", variant="secondary", size="sm")
```
to:
```python
            with gr.Column(scale=1, min_width=140):
                gr.Markdown("")
```

Then, inside the `with gr.Tabs():` block, AFTER the video tab's closing (after the `vid_stop.click(...)` line, still inside `with gr.Tabs():`), add the admin and manual tabs:
```python
            # ---- 관리자 승인 ----
            with gr.Tab("🔐 관리자"):
                gr.Markdown("관리자만 사용할 수 있습니다. 가입 신청을 승인/거절합니다.")
                adm_status = gr.Textbox(label="상태", interactive=False)
                adm_pending = gr.Dropdown(choices=[], label="대기 중 신청", interactive=True)
                with gr.Row():
                    adm_refresh = gr.Button("🔄 새로고침")
                    adm_approve = gr.Button("✅ 승인", variant="primary")
                    adm_reject = gr.Button("⛔ 거절", variant="stop")

                def _adm_refresh(request: gr.Request):
                    actor = getattr(request, "username", None)
                    allowed, pending, msg = _admin_view(actor)
                    return gr.update(choices=pending, value=(pending[0] if pending else None)), msg

                def _adm_approve(selected, request: gr.Request):
                    actor = getattr(request, "username", None)
                    _, msg = admin_approve_action(selected, actor)
                    allowed, pending, _ = _admin_view(actor)
                    return gr.update(choices=pending, value=(pending[0] if pending else None)), msg

                def _adm_reject(selected, request: gr.Request):
                    actor = getattr(request, "username", None)
                    _, msg = admin_reject_action(selected, actor)
                    allowed, pending, _ = _admin_view(actor)
                    return gr.update(choices=pending, value=(pending[0] if pending else None)), msg

                adm_refresh.click(fn=_adm_refresh, inputs=None,
                                  outputs=[adm_pending, adm_status], api_name=False)
                adm_approve.click(fn=_adm_approve, inputs=[adm_pending],
                                  outputs=[adm_pending, adm_status], api_name=False)
                adm_reject.click(fn=_adm_reject, inputs=[adm_pending],
                                 outputs=[adm_pending, adm_status], api_name=False)

            # ---- 사용설명서 ----
            with gr.Tab("📖 사용설명서"):
                gr.HTML(render_manual_html())
                gr.DownloadButton("⬇️ 원본(.docx) 다운로드", value=MANUAL_DOCX, variant="secondary")
```

- [ ] **Step 5: `__main__`에서 중복 manual 코드/라우트 제거**

In the `__main__` block, DELETE the now-duplicated manual rendering and routes:
- Delete the `MANUAL_DOCX = ...` line and the entire `_manual_cache = {...}` + `def _render_manual_html(): ...` block (now at module level).
- Delete the `@app_api.get("/manual", ...) def manual_page(): ...` route.
- Delete the `@app_api.get("/manual/download", ...) def manual_download(): ...` route.

Keep `from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse` only if still used; after deleting manual routes, `FileResponse`/`PlainTextResponse` are unused — change that import line to:
```python
    from fastapi.responses import HTMLResponse
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_auth_app.py tests/test_app_ui.py -v`
Expected: PASS (test_auth_app 7 + test_app_ui 2). `test_ui_has_no_model_names_in_source` 도 통과(인증 코드에 모델명 없음).

- [ ] **Step 7: 구문 + 잔재 확인 + 회귀**

Run: `cd /home/opc/projects/image_generator && python3 -c "import ast; ast.parse(open('app.py').read()); print('OK')"`
Expected: `OK`

Run: `cd /home/opc/projects/image_generator && grep -n "_render_manual_html\|/manual" app.py || echo "no manual route refs"`
Expected: `no manual route refs` (헤더 link="manual" 버튼도 제거됨)

Run: `cd /home/opc/projects/image_generator && python3 -m pytest -q`
Expected: 46 passed (42 + 4)

- [ ] **Step 8: 커밋**

```bash
cd /home/opc/projects/image_generator
git add app.py tests/test_auth_app.py
git commit -m "feat(auth): 관리자 승인 탭 + 사용설명서 게이트 탭(공개 /manual 제거)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: README 인증 섹션

**Files:**
- Modify: `README.md`

**Interfaces:** 없음(문서).

- [ ] **Step 1: README에 인증 섹션 추가**

Add a new "## 접근 및 계정" section to `README.md` (after the 기능 section, before 백엔드 설정). Insert verbatim:
```markdown
## 접근 및 계정

스튜디오와 사용설명서는 **승인된 계정만** 접근할 수 있습니다.

- **로그인**: 첫 화면에서 아이디·비밀번호로 로그인합니다. 연속 5회 실패하면 일정 시간 잠깁니다.
- **가입**: 로그인 화면의 "가입 신청" 링크(`/signup`)에서 아이디·비밀번호로 신청합니다.
  신청은 **관리자 승인 후** 로그인할 수 있습니다.
- **관리자 승인**: 관리자 계정으로 로그인하면 "🔐 관리자" 탭에서 대기 중 신청을 승인/거절합니다.
- **최초 관리자**: 아이디 `hh09080`. 최초 실행 시 자동 생성됩니다. 비밀번호는 소유자가 보관하며,
  환경변수 `ADMIN_PASSWORD`로 교체할 수 있습니다.

```env
# (선택) 최초 관리자 비밀번호 교체 — 최초 실행(계정 생성) 전에 설정
# ADMIN_PASSWORD=...
# (선택) 로그인 시도 제한
# LOGIN_MAX_ATTEMPTS=5
# LOGIN_LOCKOUT_SECONDS=900
```

> 계정 정보는 `data/users.json`에 비밀번호 **해시**로만 저장되며 git에 커밋되지 않습니다.
```

- [ ] **Step 2: 회귀 + 누출 점검**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest -q`
Expected: 46 passed

Run: `cd /home/opc/projects/image_generator && grep -niE "hh07290729" README.md app.py auth/store.py || echo "평문 비밀번호 없음"`
Expected: `평문 비밀번호 없음`

- [ ] **Step 3: 커밋**

```bash
cd /home/opc/projects/image_generator
git add README.md
git commit -m "docs: 접근/계정(로그인·가입 승인·관리자) 안내 추가

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (계획 작성자 자체 점검)

**1. Spec coverage:**
- 로그인 게이트(스튜디오+설명서) → Task 2(mount auth=) + Task 3(설명서 탭 이동, /manual 제거). ✅
- admin 승인제 가입 → Task 2(공개 /signup → pending) + Task 3(관리자 탭 승인). ✅
- 시드 admin(hh09080) → Task 1(BOOTSTRAP_ADMIN, seed_admin) + Task 2(seed 호출). ✅
- 로그인 5회 제한 → Task 1(check_login + 테스트). ✅
- 평문 비커밋 → Task 1(salt+hash 임베드) + Task 4 누출 점검; data/ gitignore Task 2. ✅
- 모델명 비노출 → 인증 UI 텍스트 중립 + Task 2 signup 테스트가 누출 검사. ✅
- 신규 의존 없음 → stdlib만. ✅

**2. Placeholder scan:** 모든 코드 스텝에 실제 코드 포함. TBD/모호 표현 없음. ✅

**3. Type consistency:** `authenticate`→`store.check_login`, `signup_submit`→`store.create_pending`,
`admin_*_action`/`_admin_view`→`store.is_admin/approve/reject/list_pending` 시그니처 일치.
`render_manual_html`/`MANUAL_DOCX` Task 3 정의 = build_ui 소비 일치. `_admin_view`는 (allowed, pending, msg)
3-튜플로 Task 3 정의·테스트·핸들러에서 일관 사용. ✅

## 범위 메모
- 시드 admin 평문은 사전 계산한 salt+hash로만 임베드(plan/코드/테스트에 평문 없음). 테스트는 env ADMIN_PASSWORD
  경로 또는 자체 생성 사용자로 검증.
- 실서버 로그인/세션 동작(브라우저)·실제 잠금 UX는 수동 검증 권장(단위 테스트는 store/핸들러 로직 커버).
