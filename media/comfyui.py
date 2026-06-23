"""ComfyUI HTTP API(:8188) 얇은 클라이언트 — stdlib urllib만 사용(외부 의존 회피).

워크플로는 "API Format" JSON(node-id 키 dict) 템플릿. 단독 토큰(값 전체가 "%X%")은
원래 형(int 등)을 보존하고, 문자열 내 임베드 토큰은 문자열 치환한다.
"""
import json
import time
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


def queue_prompt(base_url, graph, client_id="studio"):
    out = _post_json(base_url.rstrip("/") + "/prompt", {"prompt": graph, "client_id": client_id})
    return out["prompt_id"]


def poll_history(base_url, prompt_id, timeout=300, interval=1.0):
    deadline = time.time() + timeout
    url = base_url.rstrip("/") + "/history/" + prompt_id
    while time.time() < deadline:
        hist = _get_json(url)
        entry = hist.get(prompt_id)
        if entry and entry.get("outputs"):
            return entry["outputs"]
        time.sleep(interval)
    raise TimeoutError("ComfyUI history timeout: %s" % prompt_id)


def first_image_ref(outputs):
    for node in (outputs or {}).values():
        for img in (node.get("images") or []):
            return {"filename": img["filename"], "subfolder": img.get("subfolder", ""),
                    "type": img.get("type", "output")}
    raise RuntimeError("ComfyUI 출력 이미지 없음")


def first_media_ref(outputs, keys=("gifs", "videos", "images")):
    for key in keys:
        for node in (outputs or {}).values():
            for m in (node.get(key) or []):
                return {"filename": m["filename"], "subfolder": m.get("subfolder", ""),
                        "type": m.get("type", "output")}
    raise RuntimeError("ComfyUI 출력 미디어 없음")


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
    with urllib.request.urlopen(req, timeout=60) as r:
        j = json.loads(r.read())
    return {"name": j.get("name", filename), "subfolder": j.get("subfolder", ""),
            "type": j.get("type", "input")}
