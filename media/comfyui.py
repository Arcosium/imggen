"""ComfyUI HTTP API(:8188) 얇은 클라이언트 — stdlib urllib만 사용(외부 의존 회피).

워크플로는 "API Format" JSON(node-id 키 dict) 템플릿. 단독 토큰(값 전체가 "%X%")은
원래 형(int 등)을 보존하고, 문자열 내 임베드 토큰은 문자열 치환한다.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def load_template(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _sub_scalar(s, tokens):
    if not isinstance(s, str):
        return s
    if s in tokens:                 # 값 전체가 토큰 → 원래 형 보존
        return tokens[s]
    for k, v in tokens.items():     # 임베드 토큰 → 문자열 치환
        if k in s:
            s = s.replace(k, str(v))
    return s


def fill_template(node, tokens):
    if isinstance(node, dict):
        return {k: fill_template(v, tokens) for k, v in node.items()}
    if isinstance(node, list):
        return [fill_template(v, tokens) for v in node]
    return _sub_scalar(node, tokens)


def _post_json(url, payload, timeout=30):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _get_json(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def ensure_up(base_url, timeout=120):
    """ComfyUI 가 내려가 있으면 올리고 준비될 때까지 기다린다.

    유휴 3분이면 comfyui-idle.timer 가 서비스를 내린다(ComfyUI 에 유휴 언로드 API 가 없어
    모델 12~13GB 가 호스트 RAM 에 주차되는 것을 프로세스 종료로 막는 구조). imggen 은
    ArcAI.ve 와 같은 ComfyUI 를 쓰는 별개 클라이언트라 여기도 기동 보장이 필요하다.
    유저 유닛이라 sudo 불필요. 떠 있으면 /queue 한 번 값만 든다."""
    # imggen.service 는 User=arcosium 시스템 유닛이라 XDG_RUNTIME_DIR 이 환경에 없다.
    # 그대로 두면 `systemctl --user` 가 유저 버스를 못 찾아 조용히 실패한다 — 명시 주입.
    env = {**os.environ,
           "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()}
    subprocess.run(["systemctl", "--user", "start", "comfyui.service"],
                   check=False, capture_output=True, timeout=60, env=env)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base_url.rstrip("/") + "/queue", timeout=3).close()
            return True
        except Exception:
            time.sleep(1)
    return False


def _retry_after_start(base_url, call):
    """호출이 연결 실패로 죽으면 ComfyUI 를 올리고 1회 재시도.
    선프로브를 두지 않아 떠 있는 정상 경로(연속 생성 중)엔 비용이 0이다."""
    try:
        return call()
    except urllib.error.URLError:
        if not ensure_up(base_url):
            raise
        return call()


def queue_prompt(base_url, graph, client_id="studio"):
    out = _retry_after_start(base_url, lambda: _post_json(
        base_url.rstrip("/") + "/prompt", {"prompt": graph, "client_id": client_id}))
    return out["prompt_id"]


def poll_history(base_url, prompt_id, timeout=300, interval=1.0):
    deadline = time.time() + timeout
    url = base_url.rstrip("/") + "/history/" + prompt_id
    while time.time() < deadline:
        hist = _get_json(url)
        entry = hist.get(prompt_id)
        if entry and entry.get("outputs"):
            return entry["outputs"]
        # 실패한 잡은 outputs 가 비어 있어 예전엔 timeout(30분)까지 헛돌았다 — 상태를 보고 바로 끝낸다.
        status = (entry or {}).get("status") or {}
        if status.get("status_str") == "error":
            msgs = [m[1].get("exception_message", "") for m in status.get("messages", [])
                    if m and m[0] == "execution_error"]
            raise RuntimeError("ComfyUI job failed: %s" % ("; ".join(msgs) or prompt_id))
        time.sleep(interval)
    raise TimeoutError("ComfyUI history timeout: %s" % prompt_id)


def first_image_ref(outputs):
    for node in (outputs or {}).values():
        for img in (node.get("images") or []):
            return {"filename": img["filename"], "subfolder": img.get("subfolder", ""),
                    "type": img.get("type", "output")}
    raise RuntimeError("ComfyUI 출력 이미지 없음")


def free_memory(base_url, *, unload_models=True, free=True, timeout=30):
    """모델/메모리 해제(POST /free). 단계 사이 언로드로 피크 1모델 보장. 베스트에포트."""
    try:
        _post_json(base_url.rstrip("/") + "/free",
                   {"unload_models": unload_models, "free_memory": free}, timeout=timeout)
        return True
    except Exception:
        return False


def fetch_media(base_url, ref):
    query = urllib.parse.urlencode({"filename": ref["filename"], "subfolder": ref.get("subfolder", ""),
                                    "type": ref.get("type", "output")})
    with urllib.request.urlopen(base_url.rstrip("/") + "/view?" + query, timeout=120) as r:
        return r.read()


def upload_image(base_url, image_bytes, filename="studio_input.png"):
    boundary = "----Studio" + uuid.uuid4().hex
    body = (
        ("--%s\r\n" % boundary).encode()
        + ('Content-Disposition: form-data; name="image"; filename="%s"\r\n' % filename).encode()
        + b"Content-Type: image/png\r\n\r\n" + image_bytes + b"\r\n"
        + ("--%s\r\n" % boundary).encode()
        + b'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n'
        + ("--%s--\r\n" % boundary).encode()
    )
    req = urllib.request.Request(base_url.rstrip("/") + "/upload/image", data=body,
                                 headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary})

    def _send():                 # 편집 경로는 업로드가 큐잉보다 먼저 — 여기도 기동 보장
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    j = _retry_after_start(base_url, _send)
    return {"name": j.get("name", filename), "subfolder": j.get("subfolder", ""),
            "type": j.get("type", "input")}
