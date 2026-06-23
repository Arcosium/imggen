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
