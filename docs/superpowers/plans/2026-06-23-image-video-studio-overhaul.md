# Image & Video Studio 전면 개편 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** image_generator(Gradio 앱)의 이미지·비디오 스튜디오를 ArcAI.ve의 로컬 ComfyUI 미디어 파이프라인을 참고해 전면 개편하되, 사용자에게 모델명을 일절 노출하지 않는다.

**Architecture:** ArcAI.ve의 모듈형 파이프라인(comfyui 클라이언트 / 설정 / 다단계 파이프라인)을 `media/` 패키지로 이식한다. ArcAI.ve의 잡-스토어/폴링(`media_jobs.py`)은 Gradio 제너레이터 `yield`로 대체해 생략한다. `media/`는 Gradio에 의존하지 않아 단위 테스트가 빠르다. app.py는 모델명 없는 2탭 스튜디오 UI + 와이어링만 담당한다.

**Tech Stack:** Python 3, Gradio 5, FastAPI/uvicorn(마운트), stdlib `urllib`(ComfyUI/LLM HTTP), pytest(테스트), ComfyUI(런타임 백엔드, 외부).

## Global Constraints

- **모델명 비노출**: 사용자 노출 표면(UI 라벨/탭/상태/에러/README의 사용자 안내)에 FLUX·Qwen·Wan·Veo·Gemini·Imagen·ComfyUI 등 모델/엔진 고유명 금지. 기능 중심 중립 표현만("이미지 생성", "고화질 편집", "영상화"). 체크포인트 파일명은 워크플로 JSON/env(운영자 대상)엔 허용되나 UI엔 절대 노출 금지.
- **신규 외부 의존 금지**: ComfyUI/LLM HTTP는 stdlib `urllib`로 구현(`requests` 추가 금지 — PyInstaller `.exe` 배포 고려). `requirements.txt`에서 `google-genai` 제거.
- **백엔드 부재 내성**: ComfyUI/LLM이 없어도 앱은 정상 기동한다. 생성 시도 시에만 친절한 일반화 에러("이미지 백엔드에 연결할 수 없습니다"). 내부 예외 메시지를 사용자에게 노출하지 않는다.
- **프롬프트 확장 폴백**: 프롬프트 확장은 기본 ON이지만, LLM 백엔드 미설정/실패 시 예외 없이 원문 프롬프트로 폴백한다.
- **NSFW 게이팅**: NSFW는 서버 env `IMAGE_NSFW_ENABLED` 가 켜진 경우에만 실효. 아니면 SFW로 강등.
- **테스트 실행**: `cd /home/opc/projects/image_generator && python3 -m pytest`. `media/` 테스트는 gradio를 import하지 않는다.
- **커밋 메시지 말미**: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task 1: `media/` 패키지 + `backend.py` (설정 단일 소스)

**Files:**
- Create: `media/__init__.py`
- Create: `media/backend.py`
- Create: `tests/__init__.py`
- Create: `tests/test_backend.py`

**Interfaces:**
- Produces:
  - `ASPECTS: dict[str, tuple[int, int]]`
  - `aspect_dims(name: str) -> tuple[int, int]`
  - `nsfw_enabled(requested: bool) -> bool`
  - `resolve_image_mode(requested: str | None) -> str`  # "sfw" | "uncensored"
  - `image_config() -> dict`  # keys: base_url, txt2img_workflow, edit_workflow, ckpt, t5, clip_l, vae, nsfw_lora, nsfw_lora_weight
  - `video_config() -> dict`  # keys: base_url, i2v_workflow, video_ckpt, t5, vae, frames, fps, steps, cfg
  - `llm_config() -> dict`    # keys: enabled, base_url, api_key, model, timeout

- [ ] **Step 1: 패키지 init 파일 생성**

Create `media/__init__.py`:
```python
"""로컬 ComfyUI 미디어 생성 파이프라인(이미지/비디오). Gradio 비의존."""
```

Create `tests/__init__.py` (빈 파일):
```python
```

- [ ] **Step 2: 실패하는 테스트 작성**

Create `tests/test_backend.py`:
```python
import importlib

from media import backend


def test_aspect_dims_known():
    assert backend.aspect_dims("9:16") == (576, 1024)
    assert backend.aspect_dims("16:9") == (1024, 576)
    assert backend.aspect_dims("1:1") == (1024, 1024)


def test_aspect_dims_unknown_falls_back_to_square():
    assert backend.aspect_dims("garbage") == (1024, 1024)
    assert backend.aspect_dims("") == (1024, 1024)
    assert backend.aspect_dims(None) == (1024, 1024)


def test_resolve_image_mode_downgrades_without_server_flag(monkeypatch):
    monkeypatch.delenv("IMAGE_NSFW_ENABLED", raising=False)
    assert backend.resolve_image_mode("uncensored") == "sfw"
    assert backend.resolve_image_mode("sfw") == "sfw"
    assert backend.resolve_image_mode(None) == "sfw"


def test_resolve_image_mode_honored_when_server_flag_on(monkeypatch):
    monkeypatch.setenv("IMAGE_NSFW_ENABLED", "1")
    assert backend.resolve_image_mode("uncensored") == "uncensored"
    assert backend.resolve_image_mode("sfw") == "sfw"


def test_image_config_defaults_point_to_packaged_workflows():
    cfg = backend.image_config()
    assert cfg["base_url"] == "http://127.0.0.1:8188"
    assert cfg["txt2img_workflow"].endswith("workflows/txt2img.json")
    assert cfg["edit_workflow"].endswith("workflows/edit.json")
    assert cfg["nsfw_lora_weight"] == 0.9


def test_video_config_defaults():
    cfg = backend.video_config()
    assert cfg["i2v_workflow"].endswith("workflows/i2v.json")
    assert cfg["frames"] == 49
    assert cfg["fps"] == 16


def test_llm_config_enabled_flag_follows_base_url(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("IMAGE_PROMPT_LLM_BASE_URL", raising=False)
    assert backend.llm_config()["enabled"] is False
    monkeypatch.setenv("IMAGE_PROMPT_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    cfg = backend.llm_config()
    assert cfg["enabled"] is True
    assert cfg["base_url"] == "http://127.0.0.1:11434/v1"
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_backend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'media.backend'`

- [ ] **Step 4: `backend.py` 구현**

Create `media/backend.py`:
```python
"""미디어 생성 백엔드 설정의 단일 소스.

env 미설정 시 모든 값이 로컬 ComfyUI 기본값(127.0.0.1:8188)으로 떨어진다.
이 모듈은 Gradio/파이프라인을 import하지 않는다(순환 방지). 모델 체크포인트 이름은
여기(운영자 대상 설정)에 모이며, 사용자 UI엔 절대 노출되지 않는다.
"""
import os

ASPECTS = {
    "1:1": (1024, 1024),
    "9:16": (576, 1024),
    "16:9": (1024, 576),
    "3:4": (768, 1024),
    "4:3": (1024, 768),
}


def _flag(name, default=False):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def aspect_dims(name):
    """비율 프리셋 이름 → (width, height). 미지 이름은 1:1로 안전 폴백."""
    return ASPECTS.get((name or "").strip(), (1024, 1024))


def nsfw_enabled(requested):
    """NSFW는 서버 env IMAGE_NSFW_ENABLED 가 켜진 경우에만 실효."""
    return bool(requested) and _flag("IMAGE_NSFW_ENABLED")


def resolve_image_mode(requested):
    """공개 mode 해석. uncensored는 서버 플래그가 켜진 경우만 허용, 아니면 sfw 강등."""
    if (requested or "sfw").strip().lower() == "uncensored" and _flag("IMAGE_NSFW_ENABLED"):
        return "uncensored"
    return "sfw"


def _pkg_workflow(name):
    return os.path.join(os.path.dirname(__file__), "workflows", name)


def _base_url():
    return (os.environ.get("COMFYUI_BASE_URL") or "http://127.0.0.1:8188").rstrip("/")


def image_config():
    return {
        "base_url": _base_url(),
        "txt2img_workflow": os.environ.get("COMFYUI_TXT2IMG_WORKFLOW") or _pkg_workflow("txt2img.json"),
        "edit_workflow": os.environ.get("COMFYUI_EDIT_WORKFLOW") or _pkg_workflow("edit.json"),
        "ckpt": os.environ.get("COMFYUI_CKPT") or "FHDR_ComfyUI-Q8_0.gguf",
        "edit_ckpt": os.environ.get("COMFYUI_EDIT_CKPT") or "Qwen-Image-Edit-2511-Q8_0.gguf",
        "t5": os.environ.get("COMFYUI_T5") or "t5xxl_fp8_e4m3fn.safetensors",
        "clip_l": os.environ.get("COMFYUI_CLIP_L") or "clip_l.safetensors",
        "vae": os.environ.get("COMFYUI_VAE") or "ae.safetensors",
        "nsfw_lora": os.environ.get("COMFYUI_NSFW_LORA") or "qwen-image-edit-plus-nsfw-lora.safetensors",
        "nsfw_lora_weight": float(os.environ.get("COMFYUI_NSFW_LORA_WEIGHT") or "0.9"),
    }


def video_config():
    return {
        "base_url": _base_url(),
        "i2v_workflow": os.environ.get("COMFYUI_I2V_WORKFLOW") or _pkg_workflow("i2v.json"),
        "video_ckpt": os.environ.get("COMFYUI_VIDEO_MODEL") or "10Eros_v1-Q4_K_M.gguf",
        "t5": os.environ.get("COMFYUI_T5") or "t5xxl_fp8_e4m3fn.safetensors",
        "vae": os.environ.get("COMFYUI_VAE") or "ae.safetensors",
        "frames": int(os.environ.get("COMFYUI_VIDEO_FRAMES") or "49"),
        "fps": int(os.environ.get("COMFYUI_VIDEO_FPS") or "16"),
        "steps": int(os.environ.get("COMFYUI_VIDEO_STEPS") or "20"),
        "cfg": float(os.environ.get("COMFYUI_VIDEO_CFG") or "6.0"),
    }


def llm_config():
    """프롬프트 확장용 OpenAI-호환 LLM 설정. base_url 미설정이면 enabled=False(확장 폴백)."""
    base = (os.environ.get("IMAGE_PROMPT_LLM_BASE_URL")
            or os.environ.get("LOCAL_LLM_BASE_URL") or "").rstrip("/")
    return {
        "enabled": bool(base),
        "base_url": base,
        "api_key": os.environ.get("IMAGE_PROMPT_LLM_API_KEY") or os.environ.get("LOCAL_LLM_API_KEY") or "local",
        "model": os.environ.get("IMAGE_PROMPT_LLM_MODEL") or os.environ.get("LOCAL_LLM_MODEL") or "local-model",
        "timeout": int(os.environ.get("IMAGE_PROMPT_LLM_TIMEOUT") or "30"),
    }
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_backend.py -v`
Expected: PASS (7 passed)

- [ ] **Step 6: 커밋**

```bash
cd /home/opc/projects/image_generator
git add media/__init__.py media/backend.py tests/__init__.py tests/test_backend.py
git commit -m "feat(media): 설정 단일 소스 backend.py + 비율/NSFW 게이팅

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `media/comfyui.py` (얇은 ComfyUI HTTP 클라이언트, urllib)

**Files:**
- Create: `media/comfyui.py`
- Create: `tests/test_comfyui.py`

**Interfaces:**
- Produces:
  - `load_template(path: str) -> dict`
  - `fill_template(node, tokens: dict)`  # 재귀 토큰 치환, 단독 토큰은 원래 형 보존
  - `queue_prompt(base_url: str, graph: dict, client_id="studio") -> str`
  - `poll_history(base_url: str, prompt_id: str, timeout=300, interval=1.0) -> dict`
  - `first_image_ref(outputs: dict) -> dict`  # {filename, subfolder, type}
  - `first_media_ref(outputs: dict, keys=("gifs","videos","images")) -> dict`
  - `free_memory(base_url: str, *, unload_models=True, free=True, timeout=30) -> bool`
  - `fetch_media(base_url: str, ref: dict) -> bytes`
  - `upload_image(base_url: str, image_bytes: bytes, filename="studio_input.png") -> dict`  # {"name": ...}

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_comfyui.py`:
```python
import io
import json

from media import comfyui


def test_fill_template_preserves_scalar_token_type():
    graph = {"node": {"inputs": {"width": "%WIDTH%", "text": "a %POSITIVE% b"}}}
    out = comfyui.fill_template(graph, {"%WIDTH%": 576, "%POSITIVE%": "cat"})
    # 값 전체가 토큰이면 원래 형(int) 보존
    assert out["node"]["inputs"]["width"] == 576
    assert isinstance(out["node"]["inputs"]["width"], int)
    # 문자열 내 임베드 토큰은 문자열 치환
    assert out["node"]["inputs"]["text"] == "a cat b"


def test_fill_template_recurses_lists():
    graph = {"n": {"inputs": {"latent": ["14", 0], "seed": "%SEED%"}}}
    out = comfyui.fill_template(graph, {"%SEED%": 7})
    assert out["n"]["inputs"]["latent"] == ["14", 0]
    assert out["n"]["inputs"]["seed"] == 7


def test_first_image_ref_extracts_first():
    outputs = {"17": {"images": [
        {"filename": "a.png", "subfolder": "", "type": "output"},
        {"filename": "b.png"},
    ]}}
    assert comfyui.first_image_ref(outputs) == {"filename": "a.png", "subfolder": "", "type": "output"}


def test_first_media_ref_prefers_videos_over_images():
    outputs = {
        "39": {"gifs": [{"filename": "clip.mp4", "subfolder": "", "type": "output"}]},
        "16": {"images": [{"filename": "frame.png"}]},
    }
    ref = comfyui.first_media_ref(outputs)
    assert ref["filename"] == "clip.mp4"


def test_first_image_ref_raises_when_empty():
    import pytest
    with pytest.raises(RuntimeError):
        comfyui.first_image_ref({})


def test_queue_prompt_posts_and_returns_id(monkeypatch):
    captured = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"prompt_id": "pid-123"}).encode()

    def _fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode())
        return _Resp()

    monkeypatch.setattr(comfyui.urllib.request, "urlopen", _fake_urlopen)
    pid = comfyui.queue_prompt("http://x:8188", {"1": {}}, client_id="studio")
    assert pid == "pid-123"
    assert captured["url"] == "http://x:8188/prompt"
    assert captured["data"]["client_id"] == "studio"


def test_free_memory_swallows_errors(monkeypatch):
    def _boom(req, timeout=0):
        raise OSError("connection refused")

    monkeypatch.setattr(comfyui.urllib.request, "urlopen", _boom)
    assert comfyui.free_memory("http://x:8188") is False
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_comfyui.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'media.comfyui'`

- [ ] **Step 3: `comfyui.py` 구현**

Create `media/comfyui.py`:
```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_comfyui.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: 커밋**

```bash
cd /home/opc/projects/image_generator
git add media/comfyui.py tests/test_comfyui.py
git commit -m "feat(media): urllib 기반 얇은 ComfyUI 클라이언트

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `media/llm.py` (프롬프트 확장 + 안전 폴백)

**Files:**
- Create: `media/llm.py`
- Create: `tests/test_llm.py`

**Interfaces:**
- Consumes: `backend.llm_config()` (Task 1)
- Produces:
  - `expand_prompt(idea: str, *, aspect="1:1", style="photoreal") -> str`  # 실패/미설정 시 idea 원문 반환

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_llm.py`:
```python
import json

from media import llm


def test_expand_returns_raw_when_llm_disabled(monkeypatch):
    monkeypatch.delenv("IMAGE_PROMPT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    assert llm.expand_prompt("a cat") == "a cat"


def test_expand_calls_llm_when_enabled(monkeypatch):
    monkeypatch.setenv("IMAGE_PROMPT_LLM_BASE_URL", "http://x:11434/v1")

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "  a photoreal cat, cinematic  "}}]}).encode()

    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout=0: _Resp())
    out = llm.expand_prompt("a cat")
    assert out == "a photoreal cat, cinematic"


def test_expand_falls_back_to_raw_on_error(monkeypatch):
    monkeypatch.setenv("IMAGE_PROMPT_LLM_BASE_URL", "http://x:11434/v1")

    def _boom(req, timeout=0):
        raise OSError("refused")

    monkeypatch.setattr(llm.urllib.request, "urlopen", _boom)
    assert llm.expand_prompt("a cat") == "a cat"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'media.llm'`

- [ ] **Step 3: `llm.py` 구현**

Create `media/llm.py`:
```python
"""짧은 아이디어를 고화질 영문 이미지 프롬프트로 확장(OpenAI-호환 /chat/completions).

LLM 백엔드가 미설정(backend.llm_config().enabled=False)이거나 호출이 실패하면
예외를 던지지 않고 원문(idea)을 그대로 반환한다(안전 폴백). urllib만 사용.
"""
import json
import urllib.request

from media import backend

_EXPAND_SYSTEM = (
    "You are a prompt engineer for a photoreal image model. Expand the user's idea into "
    "ONE vivid, ultra-detailed English image prompt. No refusals, no preamble — output only "
    "the prompt. Favor photoreal, cinematic, high detail."
)


def _chat(messages, *, temperature=0.7, max_tokens=400):
    cfg = backend.llm_config()
    payload = {"model": cfg["model"], "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    req = urllib.request.Request(
        cfg["base_url"] + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + cfg["api_key"]},
    )
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
        out = json.loads(r.read())
    return out["choices"][0]["message"]["content"].strip()


def expand_prompt(idea, *, aspect="1:1", style="photoreal"):
    cfg = backend.llm_config()
    if not cfg["enabled"] or not (idea or "").strip():
        return idea
    w, h = backend.aspect_dims(aspect)
    ask = "Idea: %s\nStyle: %s\nTarget aspect: %dx%d. Write the image prompt now." % (idea, style, w, h)
    try:
        result = _chat([{"role": "system", "content": _EXPAND_SYSTEM},
                        {"role": "user", "content": ask}])
        return result or idea
    except Exception:
        return idea
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_llm.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
cd /home/opc/projects/image_generator
git add media/llm.py tests/test_llm.py
git commit -m "feat(media): 프롬프트 확장 LLM 호출 + 안전 폴백

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 워크플로 템플릿 JSON 3종 (중립 파일명)

**Files:**
- Create: `media/workflows/txt2img.json`
- Create: `media/workflows/edit.json`
- Create: `media/workflows/i2v.json`
- Create: `tests/test_workflows.py`

**Interfaces:**
- Consumes: `backend.image_config()`/`video_config()` 워크플로 경로, `comfyui.fill_template` (Tasks 1-2)
- Produces: 패키지에 포함된 3종 워크플로(파이프라인이 토큰 치환해 사용)

**Note:** ArcAI.ve `comfyui_workflows/` 3종을 그대로 복사하되 파일명을 중립화하고 `filename_prefix`를 중립값("studio")으로 바꾼다. 토큰명은 파이프라인(Task 5)이 의존하므로 변경 금지.

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_workflows.py`:
```python
import json

from media import backend, comfyui


def test_txt2img_template_fills_all_tokens():
    cfg = backend.image_config()
    graph = comfyui.fill_template(comfyui.load_template(cfg["txt2img_workflow"]), {
        "%POSITIVE%": "a cat", "%NEGATIVE%": "", "%WIDTH%": 576, "%HEIGHT%": 1024,
        "%SEED%": 0, "%STEPS%": 24, "%CFG%": 3.5, "%CKPT%": cfg["ckpt"],
        "%T5%": cfg["t5"], "%CLIP_L%": cfg["clip_l"], "%VAE%": cfg["vae"],
    })
    blob = json.dumps(graph)
    assert "%" not in blob  # 모든 토큰 치환됨
    assert graph["14"]["inputs"]["width"] == 576  # 단독 토큰 int 보존


def test_i2v_template_has_video_combine_node():
    cfg = backend.video_config()
    tpl = comfyui.load_template(cfg["i2v_workflow"])
    classes = {n["class_type"] for n in tpl.values()}
    assert "VHS_VideoCombine" in classes
    assert "WanImageToVideo" in classes


def test_edit_template_has_lora_weight_token():
    cfg = backend.image_config()
    raw = json.dumps(comfyui.load_template(cfg["edit_workflow"]))
    assert "%LORA_WEIGHT%" in raw
    assert "%INPUT_IMAGE%" in raw
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_workflows.py -v`
Expected: FAIL — `FileNotFoundError` (워크플로 파일 없음)

- [ ] **Step 3: 워크플로 파일 생성**

Create `media/workflows/txt2img.json`:
```json
{
  "10": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "%CKPT%"}},
  "11": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "%T5%", "clip_name2": "%CLIP_L%", "type": "flux"}},
  "12": {"class_type": "VAELoader", "inputs": {"vae_name": "%VAE%"}},
  "13": {"class_type": "CLIPTextEncode", "inputs": {"text": "%POSITIVE%", "clip": ["11", 0]}},
  "14": {"class_type": "EmptyLatentImage", "inputs": {"width": "%WIDTH%", "height": "%HEIGHT%", "batch_size": 1}},
  "15": {"class_type": "KSampler", "inputs": {"seed": "%SEED%", "steps": "%STEPS%", "cfg": "%CFG%", "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0, "model": ["10", 0], "positive": ["13", 0], "negative": ["13", 0], "latent_image": ["14", 0]}},
  "16": {"class_type": "VAEDecode", "inputs": {"samples": ["15", 0], "vae": ["12", 0]}},
  "17": {"class_type": "SaveImage", "inputs": {"filename_prefix": "studio", "images": ["16", 0]}}
}
```

Create `media/workflows/edit.json`:
```json
{
  "20": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "%EDIT_CKPT%"}},
  "21": {"class_type": "LoraLoaderModelOnly", "inputs": {"lora_name": "%LORA_NAME%", "strength_model": "%LORA_WEIGHT%", "model": ["20", 0]}},
  "22": {"class_type": "LoadImage", "inputs": {"image": "%INPUT_IMAGE%"}},
  "23": {"class_type": "CLIPTextEncode", "inputs": {"text": "%POSITIVE%", "clip": ["20", 1]}},
  "24": {"class_type": "VAEEncode", "inputs": {"pixels": ["22", 0], "vae": ["20", 2]}},
  "25": {"class_type": "KSampler", "inputs": {"seed": "%SEED%", "steps": "%STEPS%", "cfg": "%CFG%", "sampler_name": "euler", "scheduler": "simple", "denoise": "%DENOISE%", "model": ["21", 0], "positive": ["23", 0], "negative": ["23", 0], "latent_image": ["24", 0]}},
  "26": {"class_type": "VAEDecode", "inputs": {"samples": ["25", 0], "vae": ["20", 2]}},
  "27": {"class_type": "SaveImage", "inputs": {"filename_prefix": "studio_edit", "images": ["26", 0]}}
}
```

Create `media/workflows/i2v.json`:
```json
{
  "30": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "%VIDEO_CKPT%"}},
  "31": {"class_type": "CLIPLoader", "inputs": {"clip_name": "%T5%", "type": "wan"}},
  "32": {"class_type": "VAELoader", "inputs": {"vae_name": "%VAE%"}},
  "33": {"class_type": "LoadImage", "inputs": {"image": "%INPUT_IMAGE%"}},
  "34": {"class_type": "CLIPTextEncode", "inputs": {"text": "%POSITIVE%", "clip": ["31", 0]}},
  "35": {"class_type": "CLIPTextEncode", "inputs": {"text": "%NEGATIVE%", "clip": ["31", 0]}},
  "36": {"class_type": "WanImageToVideo", "inputs": {"width": "%WIDTH%", "height": "%HEIGHT%", "length": "%FRAMES%", "batch_size": 1, "positive": ["34", 0], "negative": ["35", 0], "vae": ["32", 0], "start_image": ["33", 0]}},
  "37": {"class_type": "KSampler", "inputs": {"seed": "%SEED%", "steps": "%STEPS%", "cfg": "%CFG%", "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0, "model": ["30", 0], "positive": ["34", 0], "negative": ["35", 0], "latent_image": ["36", 0]}},
  "38": {"class_type": "VAEDecode", "inputs": {"samples": ["37", 0], "vae": ["32", 0]}},
  "39": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["38", 0], "frame_rate": "%FPS%", "format": "video/h264-mp4", "filename_prefix": "studio_vid"}}
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_workflows.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
cd /home/opc/projects/image_generator
git add media/workflows/txt2img.json media/workflows/edit.json media/workflows/i2v.json tests/test_workflows.py
git commit -m "feat(media): 중립 파일명 ComfyUI 워크플로 템플릿 3종

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `media/pipeline.py` (다단계 파이프라인 + i2v/t2v)

**Files:**
- Create: `media/pipeline.py`
- Create: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `backend.*`, `comfyui.*`, `llm.expand_prompt` (Tasks 1-4)
- Produces:
  - `txt2img(prompt, *, aspect="1:1", seed=0) -> bytes`
  - `edit_image(image_bytes, instructions, *, mode="sfw", seed=0, denoise=0.7) -> bytes`
  - `img2video(image_bytes, prompt, *, aspect="9:16", negative="", seed=0) -> tuple[bytes, str]`
  - `make_image(*, idea=None, prompt=None, aspect="1:1", mode="sfw", edit_instructions=None, expand=True, on_stage=None) -> dict`
  - `make_video(*, idea=None, prompt=None, aspect="9:16", mode="sfw", edit_instructions=None, input_image=None, expand=True, on_stage=None) -> dict`

편집 발동 규칙(ArcAI.ve와 동일): `mode=="uncensored"` 또는 `edit_instructions` 가 있을 때만 edit 단계 실행.
make_video 분기: `input_image` 가 주어지면 i2v 직행(expand/txt2img/edit 생략), 아니면 t2v 전 파이프라인.

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_pipeline.py`:
```python
from media import pipeline


def _stub_comfyui(monkeypatch, *, image=b"IMG", video=b"VID"):
    """comfyui/llm을 전부 목킹 — 네트워크 없이 단계 순서/분기만 검증."""
    calls = {"queued": [], "freed": 0}
    monkeypatch.setattr(pipeline.comfyui, "load_template", lambda p: {"t": p})
    monkeypatch.setattr(pipeline.comfyui, "fill_template", lambda g, tok: {"tokens": tok})
    monkeypatch.setattr(pipeline.comfyui, "upload_image", lambda url, b, **k: {"name": "up.png"})

    def _queue(url, graph, **k):
        calls["queued"].append(graph)
        return "pid"
    monkeypatch.setattr(pipeline.comfyui, "queue_prompt", _queue)
    monkeypatch.setattr(pipeline.comfyui, "poll_history", lambda url, pid, **k: {"out": {}})
    monkeypatch.setattr(pipeline.comfyui, "first_image_ref", lambda o: {"filename": "a.png"})
    monkeypatch.setattr(pipeline.comfyui, "first_media_ref", lambda o: {"filename": "clip.mp4"})

    def _fetch(url, ref):
        return video if ref["filename"].endswith(".mp4") else image
    monkeypatch.setattr(pipeline.comfyui, "fetch_media", _fetch)

    def _free(url, **k):
        calls["freed"] += 1
        return True
    monkeypatch.setattr(pipeline.comfyui, "free_memory", _free)
    monkeypatch.setattr(pipeline.llm, "expand_prompt", lambda idea, **k: "EXPANDED:" + idea)
    return calls


def test_make_image_sfw_no_instructions_skips_edit(monkeypatch):
    calls = _stub_comfyui(monkeypatch)
    stages = []
    res = pipeline.make_image(idea="cat", on_stage=stages.append)
    assert res["image"] == b"IMG"
    assert res["prompt_used"] == "EXPANDED:cat"
    assert stages == ["expand", "txt2img", "done"]  # edit 미발동


def test_make_image_with_instructions_runs_edit(monkeypatch):
    calls = _stub_comfyui(monkeypatch)
    stages = []
    pipeline.make_image(idea="cat", edit_instructions="make it night", on_stage=stages.append)
    assert "edit" in stages


def test_make_image_expand_off_uses_raw_prompt(monkeypatch):
    _stub_comfyui(monkeypatch)
    res = pipeline.make_image(prompt="raw prompt", expand=False)
    assert res["prompt_used"] == "raw prompt"


def test_make_video_text_runs_full_pipeline(monkeypatch):
    _stub_comfyui(monkeypatch)
    stages = []
    res = pipeline.make_video(idea="dog", on_stage=stages.append)
    assert res["video"] == b"VID"
    assert res["mime"] == "video/mp4"
    assert res["base_image"] == b"IMG"
    assert "txt2img" in stages and "img2video" in stages


def test_make_video_image_to_video_skips_generation(monkeypatch):
    _stub_comfyui(monkeypatch)
    stages = []
    res = pipeline.make_video(prompt="move", input_image=b"USERIMG", on_stage=stages.append)
    assert res["video"] == b"VID"
    assert res["base_image"] is None        # i2v 직행 — 생성 안 함
    assert "txt2img" not in stages
    assert "img2video" in stages
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'media.pipeline'`

- [ ] **Step 3: `pipeline.py` 구현**

Create `media/pipeline.py`:
```python
"""로컬 미디어 파이프라인: expand(LLM) → txt2img → edit → img2video.

SFW/NSFW 는 mode 한 값으로 갈림 — edit 단계 NSFW LoRA weight 만 0↔N 스위치.
단계 사이 free_memory 로 모델 언로드(피크 1모델). on_stage(stage) 콜백으로 진행 신호:
expand/txt2img/edit/img2video/done. make_video 는 input_image 가 있으면 i2v 직행.
"""
from media import backend, comfyui, llm


def _run_image(graph, base_url):
    pid = comfyui.queue_prompt(base_url, graph)
    outputs = comfyui.poll_history(base_url, pid)
    return comfyui.fetch_media(base_url, comfyui.first_image_ref(outputs))


def txt2img(prompt, *, aspect="1:1", seed=0, steps=24, cfg=3.5):
    ic = backend.image_config()
    w, h = backend.aspect_dims(aspect)
    graph = comfyui.fill_template(comfyui.load_template(ic["txt2img_workflow"]), {
        "%POSITIVE%": prompt, "%NEGATIVE%": "", "%WIDTH%": w, "%HEIGHT%": h,
        "%SEED%": seed, "%STEPS%": steps, "%CFG%": cfg,
        "%CKPT%": ic["ckpt"], "%T5%": ic["t5"], "%CLIP_L%": ic["clip_l"], "%VAE%": ic["vae"],
    })
    return _run_image(graph, ic["base_url"])


def edit_image(image_bytes, instructions, *, mode="sfw", seed=0, steps=20, cfg=4.0, denoise=0.7):
    ic = backend.image_config()
    weight = ic["nsfw_lora_weight"] if mode == "uncensored" else 0.0
    name = comfyui.upload_image(ic["base_url"], image_bytes)["name"]
    graph = comfyui.fill_template(comfyui.load_template(ic["edit_workflow"]), {
        "%POSITIVE%": instructions, "%INPUT_IMAGE%": name, "%SEED%": seed,
        "%STEPS%": steps, "%CFG%": cfg, "%DENOISE%": denoise,
        "%EDIT_CKPT%": ic["edit_ckpt"], "%LORA_NAME%": ic["nsfw_lora"], "%LORA_WEIGHT%": weight,
    })
    return _run_image(graph, ic["base_url"])


def img2video(image_bytes, prompt, *, aspect="9:16", negative="", seed=0):
    vc = backend.video_config()
    w, h = backend.aspect_dims(aspect)
    name = comfyui.upload_image(vc["base_url"], image_bytes)["name"]
    graph = comfyui.fill_template(comfyui.load_template(vc["i2v_workflow"]), {
        "%POSITIVE%": prompt, "%NEGATIVE%": negative, "%INPUT_IMAGE%": name,
        "%WIDTH%": w, "%HEIGHT%": h, "%FRAMES%": vc["frames"], "%FPS%": vc["fps"],
        "%SEED%": seed, "%STEPS%": vc["steps"], "%CFG%": vc["cfg"],
        "%VIDEO_CKPT%": vc["video_ckpt"], "%T5%": vc["t5"], "%VAE%": vc["vae"],
    })
    pid = comfyui.queue_prompt(vc["base_url"], graph)
    outputs = comfyui.poll_history(vc["base_url"], pid, timeout=900)
    ref = comfyui.first_media_ref(outputs)
    data = comfyui.fetch_media(vc["base_url"], ref)
    mime = "video/mp4" if ref["filename"].lower().endswith(".mp4") else "video/webm"
    return data, mime


def _resolve_prompt(idea, prompt, aspect, expand):
    if prompt and prompt.strip():
        return prompt
    if expand:
        return llm.expand_prompt(idea or "", aspect=aspect)
    return idea or ""


def make_image(*, idea=None, prompt=None, aspect="1:1", mode="sfw",
               edit_instructions=None, expand=True, on_stage=None):
    def _stage(s):
        if on_stage:
            on_stage(s)
    base_url = backend.image_config()["base_url"]
    if expand and not (prompt and prompt.strip()):
        _stage("expand")
    used = _resolve_prompt(idea, prompt, aspect, expand)
    _stage("txt2img")
    img = txt2img(used, aspect=aspect)
    if edit_instructions or mode == "uncensored":
        comfyui.free_memory(base_url)
        _stage("edit")
        img = edit_image(img, edit_instructions or "enhance and refine, keep composition", mode=mode)
    _stage("done")
    return {"image": img, "prompt_used": used}


def make_video(*, idea=None, prompt=None, aspect="9:16", mode="sfw",
               edit_instructions=None, input_image=None, expand=True, on_stage=None):
    def _stage(s):
        if on_stage:
            on_stage(s)
    base_url = backend.image_config()["base_url"]

    # 이미지→영상: 사용자 이미지를 바로 애니메이트(생성 단계 생략)
    if input_image is not None:
        used = prompt or (idea or "")
        _stage("img2video")
        video, mime = img2video(input_image, used, aspect=aspect)
        _stage("done")
        return {"video": video, "mime": mime, "base_image": None,
                "edited_image": None, "prompt_used": used}

    # 텍스트→영상: expand → txt2img → (조건부 edit) → img2video
    if expand and not (prompt and prompt.strip()):
        _stage("expand")
    used = _resolve_prompt(idea, prompt, aspect, expand)
    _stage("txt2img")
    base = txt2img(used, aspect=aspect)
    comfyui.free_memory(base_url)
    edited = None
    src = base
    if edit_instructions or mode == "uncensored":
        _stage("edit")
        edited = edit_image(base, edit_instructions or "enhance and refine, keep composition", mode=mode)
        src = edited
        comfyui.free_memory(base_url)
    _stage("img2video")
    video, mime = img2video(src, used, aspect=aspect)
    comfyui.free_memory(base_url)
    _stage("done")
    return {"video": video, "mime": mime, "base_image": base,
            "edited_image": edited, "prompt_used": used}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_pipeline.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 전체 media 테스트 회귀 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/ -v`
Expected: PASS (이전 태스크 테스트 포함 전부 통과)

- [ ] **Step 6: 커밋**

```bash
cd /home/opc/projects/image_generator
git add media/pipeline.py tests/test_pipeline.py
git commit -m "feat(media): 다단계 파이프라인 make_image/make_video (t2v+i2v)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: app.py 핸들러 재작성 + 죽은 코드 제거

**Files:**
- Modify: `app.py` (전면 재작성 — 죽은 Gemini/Imagen/Veo 코드 제거, 신규 핸들러 추가)
- Create: `tests/test_app_handlers.py`

**Interfaces:**
- Consumes: `media.pipeline.make_image/make_video` (Task 5)
- Produces (app.py 모듈 레벨):
  - `OUTPUT_DIR: str`
  - `_save_bytes(data: bytes, ext: str) -> str`  # outputs/에 타임스탬프 파일 저장, 경로 반환
  - `STAGE_LABELS: dict[str, str]`  # 단계→한국어 중립 라벨
  - `generate_image(prompt, ref_files, aspect, expand_on, edit_instr, nsfw)` → 제너레이터, yield `(status:str, image_path|None)`
  - `generate_video(mode, prompt, input_image, aspect, expand_on, nsfw)` → 제너레이터, yield `(status:str, video_path|None)`
  - `build_ui() -> gr.Blocks`

**Note:** 이 태스크는 핸들러 로직 + 죽은 코드 제거에 집중한다. UI 레이아웃(`build_ui`)은 Task 7에서 완성하되, import 가 깨지지 않도록 이 태스크 끝에 최소 `build_ui` 스텁(빈 Blocks)을 둔다.

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_app_handlers.py`:
```python
import os

import app  # gradio 는 실제 설치돼 있음(서비스가 사용). import 시 build_ui 는 호출되지 않음.


def test_generate_image_streams_status_and_path(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))

    def _fake_make_image(*, idea, prompt, aspect, mode, edit_instructions, expand, on_stage):
        on_stage("txt2img")
        on_stage("done")
        return {"image": b"PNGDATA", "prompt_used": "x"}

    monkeypatch.setattr(app.pipeline, "make_image", _fake_make_image)
    outs = list(app.generate_image("a cat", None, "1:1", True, "", False))
    final_status, final_path = outs[-1]
    assert final_path is not None and os.path.exists(final_path)
    assert open(final_path, "rb").read() == b"PNGDATA"
    assert "완료" in final_status or "✅" in final_status


def test_generate_image_handles_backend_error_gracefully(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))

    def _boom(**k):
        raise OSError("Connection refused to 127.0.0.1:8188")

    monkeypatch.setattr(app.pipeline, "make_image", _boom)
    outs = list(app.generate_image("a cat", None, "1:1", True, "", False))
    final_status, final_path = outs[-1]
    assert final_path is None
    assert "127.0.0.1" not in final_status      # 내부 세부정보 비노출
    assert "백엔드" in final_status


def test_generate_video_image_mode_requires_input(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
    outs = list(app.generate_video("이미지→영상", "move it", None, "9:16", True, False))
    final_status, final_path = outs[-1]
    assert final_path is None
    assert "이미지" in final_status
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_app_handlers.py -v`
Expected: FAIL — `AttributeError: module 'app' has no attribute 'generate_image'` (또는 import 에러)

- [ ] **Step 3: app.py 재작성 (상단~핸들러)**

Replace the entire content of `app.py` from line 1 through the end of the old `handle_modal_close` / video studio / UI helpers section, down to (but not including) `_resolve_port()`. Concretely: keep `_patch_gradio_client()` (lines 10-54), keep `_resolve_port()` and the `if __name__ == "__main__":` block (lines 1019-end) **except** remove references to deleted functions. Replace everything in between (lines 56-1016) with the code below.

The new top-of-file imports and constants:
```python
import gradio as gr
from media import backend, pipeline
import webbrowser
import threading

# =============== [ PATH / TIME ] ===============
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

KST = ZoneInfo("Asia/Seoul")


def _ts_file():
    return datetime.now(KST).strftime("%Y%m%d_%H%M%S_%f")


def _save_bytes(data, ext):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, "%s.%s" % (_ts_file(), ext))
    with open(path, "wb") as f:
        f.write(data)
    return path


# =============== [ 진행 단계 라벨 — 모델명 비노출 ] ===============
STAGE_LABELS = {
    "expand": "🧠 아이디어 다듬는 중...",
    "txt2img": "🎨 이미지 생성 중...",
    "edit": "✨ 고화질 편집 중...",
    "img2video": "🎬 영상으로 만드는 중...",
    "done": "✅ 완료",
}


def _friendly_error(exc):
    """내부 예외를 사용자용 일반 메시지로. 백엔드/소켓 세부정보 비노출."""
    return "🚨 생성에 실패했습니다. 미디어 백엔드 연결을 확인해 주세요."
```

The new image handler:
```python
def generate_image(prompt, ref_files, aspect, expand_on, edit_instr, nsfw):
    """이미지 생성 제너레이터: (상태문구, 이미지경로) 를 단계별로 yield."""
    if not (prompt and prompt.strip()) and not (edit_instr and edit_instr.strip()):
        yield "프롬프트를 입력해 주세요.", None
        return

    # 참조 이미지가 있으면 편집 소스로 사용(첫 이미지 파일)
    source_path = None
    if ref_files:
        for f in ref_files:
            if str(f).lower().rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "webp"):
                source_path = f
                break

    yield "⏳ 시작하는 중...", None
    stages = {"label": "⏳ 시작하는 중..."}

    def _on_stage(s):
        stages["label"] = STAGE_LABELS.get(s, stages["label"])

    try:
        mode = backend.resolve_image_mode("uncensored" if nsfw else "sfw")
        if source_path:
            # 참조 이미지 편집 경로: 업로드 이미지를 편집 지시로 수정
            with open(source_path, "rb") as f:
                img_bytes = f.read()
            _on_stage("edit")
            yield stages["label"], None
            edited = pipeline.edit_image(img_bytes, edit_instr or prompt, mode=mode)
            path = _save_bytes(edited, "png")
        else:
            res = pipeline.make_image(
                idea=prompt, prompt=None, aspect=aspect, mode=mode,
                edit_instructions=(edit_instr or None), expand=bool(expand_on),
                on_stage=_on_stage,
            )
            path = _save_bytes(res["image"], "png")
        yield "✅ 완료", path
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger("studio").warning("generate_image failed: %s", exc)
        yield _friendly_error(exc), None
```

The new video handler:
```python
def generate_video(mode, prompt, input_image, aspect, expand_on, nsfw):
    """비디오 생성 제너레이터: (상태문구, 영상경로) 를 단계별로 yield.
    mode: '텍스트→영상' | '이미지→영상'."""
    is_i2v = "이미지" in (mode or "")
    if is_i2v and not input_image:
        yield "이미지→영상 모드에서는 입력 이미지를 올려 주세요.", None
        return
    if not is_i2v and not (prompt and prompt.strip()):
        yield "프롬프트를 입력해 주세요.", None
        return

    yield "⏳ 시작하는 중...", None
    stages = {"label": "⏳ 시작하는 중..."}

    def _on_stage(s):
        stages["label"] = STAGE_LABELS.get(s, stages["label"])

    try:
        img_mode = backend.resolve_image_mode("uncensored" if nsfw else "sfw")
        input_bytes = None
        if is_i2v and input_image:
            with open(input_image, "rb") as f:
                input_bytes = f.read()
        res = pipeline.make_video(
            idea=prompt, prompt=(prompt if is_i2v else None), aspect=aspect,
            mode=img_mode, input_image=input_bytes, expand=bool(expand_on),
            on_stage=_on_stage,
        )
        ext = "mp4" if res["mime"] == "video/mp4" else "webm"
        path = _save_bytes(res["video"], ext)
        yield "✅ 완료", path
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger("studio").warning("generate_video failed: %s", exc)
        yield _friendly_error(exc), None
```

Add a temporary stub for build_ui at the end of this section (Task 7 replaces it):
```python
def build_ui():
    with gr.Blocks() as demo:
        gr.Markdown("UI 구성 예정")
    return demo
```

Also delete these now-unused symbols and their code if still present anywhere in the file: `IMAGE_MODEL_MAPPING`, `VIDEO_MODEL_MAPPING`, `ASPECT_RATIOS`, `RESOLUTIONS`, `THINK_LEVELS`, `SAFETY_SETTINGS`, `SYSTEM_INSTRUCTION`, `get_client`, `load_api_key`, `save_api_key`, `get_image_config`, `_build_final_prompt`, `_generate_session_title`, `_run_imagen`, `_save_history_json`, `process_image_interaction`, `reset_session`, `generate_modal_image`, `handle_modal_close`, `_generate_video_core`, `standard_vid_ui`, `extend_vid_ui`, `_list_projects`, `_load_project`, `_handle_image_select`, `_extract_text_from_doc`, and the `from google import genai` / `from google.genai import types` / `from PIL import Image` imports.

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_app_handlers.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: import 정합성 확인 (죽은 코드 잔재 없음)**

Run: `cd /home/opc/projects/image_generator && python3 -c "import ast,sys; ast.parse(open('app.py').read()); print('app.py parses OK')"`
Expected: `app.py parses OK`

Run: `cd /home/opc/projects/image_generator && grep -nE "genai|veo|imagen|Gemini|VIDEO_MODEL_MAPPING|IMAGE_MODEL_MAPPING|process_image_interaction" app.py || echo "no dead refs"`
Expected: `no dead refs`

- [ ] **Step 6: 커밋**

```bash
cd /home/opc/projects/image_generator
git add app.py tests/test_app_handlers.py
git commit -m "refactor(app): 파이프라인 기반 핸들러로 재작성 + Gemini/Veo 죽은 코드 제거

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: app.py `build_ui()` — 2탭 스튜디오 레이아웃

**Files:**
- Modify: `app.py` (`build_ui` 스텁을 실제 2탭 UI로 교체)
- Create: `tests/test_app_ui.py`

**Interfaces:**
- Consumes: `generate_image`, `generate_video`, `backend.ASPECTS` (Task 6, Task 1)
- Produces: `build_ui() -> gr.Blocks` (실제 레이아웃)

**Note:** UI 텍스트는 전부 중립(모델명 금지). API 키 입력칸 없음.

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_app_ui.py`:
```python
import app


def test_build_ui_constructs_without_error():
    demo = app.build_ui()
    assert demo is not None


def test_ui_has_no_model_names_in_source():
    src = open("app.py", encoding="utf-8").read()
    banned = ["FLUX", "Qwen", "Veo", "Gemini", "Imagen", "ComfyUI", "Wan"]
    leaked = [w for w in banned if w in src]
    assert leaked == [], "모델명 누출: %s" % leaked
```

- [ ] **Step 2: 테스트 실행 (UI 스텁이라 test 1은 통과, test 2는 잔재 따라 다름)**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_app_ui.py -v`
Expected: `test_build_ui_constructs_without_error` PASS. `test_ui_has_no_model_names_in_source`는 이 시점엔 워크플로 주석 등 잔재가 없으면 PASS — 실패하면 잔재 제거.

- [ ] **Step 3: `build_ui()` 실제 구현으로 교체**

Replace the temporary `build_ui` stub with:
```python
CSS = """
body.dark { font-family: 'Pretendard', sans-serif; background-color: #121212 !important; color: #fff !important; }
#result-img, #result-vid { border-radius: 12px; background:#1e1e1e !important; border:1px solid #333; }
#sidebar { background:#181818 !important; padding:18px; border-radius:12px; border:1px solid #333; }
"""

JS_CODE = """
function() {
    document.body.classList.add("dark");
    document.querySelector("gradio-app").classList.add("dark");
    window.addEventListener("beforeunload", function () { navigator.sendBeacon('/shutdown'); });
}
"""


def build_ui():
    aspects = list(backend.ASPECTS.keys())
    with gr.Blocks(theme=gr.themes.Base(), css=CSS, js=JS_CODE) as demo:
        with gr.Row():
            with gr.Column(scale=8):
                gr.Markdown("# 🚀 Image & Video Studio")
                gr.Markdown("Made by Hyunho Kim · <CONTACT_EMAIL>")
            with gr.Column(scale=1, min_width=140):
                gr.Button("📖 사용설명서", link="manual", variant="secondary", size="sm")

        with gr.Tabs():
            # ---- 이미지 스튜디오 ----
            with gr.Tab("🎨 이미지 스튜디오"):
                with gr.Row():
                    with gr.Column(scale=2, elem_id="sidebar"):
                        img_prompt = gr.Textbox(label="프롬프트", lines=4,
                                                placeholder="만들고 싶은 이미지를 자유롭게 적어 주세요.")
                        img_aspect = gr.Dropdown(choices=aspects, value="1:1", label="비율")
                        img_ref = gr.File(file_count="multiple",
                                          label="참조 이미지(편집할 원본, 선택)")
                        with gr.Accordion("고급 설정", open=False):
                            img_expand = gr.Checkbox(label="프롬프트 자동 다듬기", value=True)
                            img_edit_instr = gr.Textbox(label="편집 지시(참조 이미지 수정 내용)",
                                                        lines=2, placeholder="예: 배경을 밤으로 바꿔줘")
                            img_nsfw = gr.Checkbox(label="제한 해제 편집 모드", value=False)
                        with gr.Row():
                            img_go = gr.Button("✨ 생성", variant="primary")
                            img_stop = gr.Button("⏹️ 중지", variant="stop")
                    with gr.Column(scale=3):
                        img_status = gr.Textbox(label="진행 상태", interactive=False)
                        img_out = gr.Image(label="결과", elem_id="result-img", height=520,
                                           type="filepath", interactive=False)
                        img_dl = gr.DownloadButton("⬇️ 다운로드", variant="secondary")

                img_evt = img_go.click(
                    fn=generate_image,
                    inputs=[img_prompt, img_ref, img_aspect, img_expand, img_edit_instr, img_nsfw],
                    outputs=[img_status, img_out], api_name=False,
                )
                img_stop.click(fn=None, inputs=None, outputs=None, cancels=[img_evt], api_name=False)
                img_out.change(fn=lambda p: gr.update(value=p), inputs=[img_out],
                               outputs=[img_dl], api_name=False)

            # ---- 비디오 스튜디오 ----
            with gr.Tab("🎬 비디오 스튜디오"):
                with gr.Row():
                    with gr.Column(scale=2, elem_id="sidebar"):
                        vid_mode = gr.Radio(choices=["텍스트→영상", "이미지→영상"],
                                            value="텍스트→영상", label="모드")
                        vid_prompt = gr.Textbox(label="프롬프트", lines=4,
                                                placeholder="영상으로 만들 장면을 적어 주세요.")
                        vid_input = gr.Image(label="입력 이미지(이미지→영상 모드)", type="filepath",
                                             visible=False)
                        vid_aspect = gr.Dropdown(choices=["9:16", "16:9", "1:1"], value="9:16",
                                                 label="비율")
                        with gr.Accordion("고급 설정", open=False):
                            vid_expand = gr.Checkbox(label="프롬프트 자동 다듬기", value=True)
                            vid_nsfw = gr.Checkbox(label="제한 해제 편집 모드", value=False)
                        with gr.Row():
                            vid_go = gr.Button("🎬 생성", variant="primary")
                            vid_stop = gr.Button("⏹️ 중지", variant="stop")
                    with gr.Column(scale=3):
                        vid_status = gr.Textbox(label="진행 상태", interactive=False)
                        vid_out = gr.Video(label="결과", elem_id="result-vid", height=520)

                vid_mode.change(
                    fn=lambda m: gr.update(visible=("이미지" in m)),
                    inputs=[vid_mode], outputs=[vid_input], api_name=False,
                )
                vid_evt = vid_go.click(
                    fn=generate_video,
                    inputs=[vid_mode, vid_prompt, vid_input, vid_aspect, vid_expand, vid_nsfw],
                    outputs=[vid_status, vid_out], api_name=False,
                )
                vid_stop.click(fn=None, inputs=None, outputs=None, cancels=[vid_evt], api_name=False)

    return demo
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/test_app_ui.py -v`
Expected: PASS (2 passed). `test_ui_has_no_model_names_in_source` 실패 시 해당 단어 제거.

- [ ] **Step 5: 전체 테스트 회귀**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/ -v`
Expected: 전부 PASS

- [ ] **Step 6: 수동 기동 스모크(선택, 백엔드 없이 UI만)**

Run: `cd /home/opc/projects/image_generator && timeout 12 python3 app.py & sleep 9 && curl -s -m 3 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8503/ ; kill %1 2>/dev/null`
Expected: `200` (Gradio UI가 뜸). 포트 충돌 시 `APP_PORT=7870` 등으로 재시도.

- [ ] **Step 7: 커밋**

```bash
cd /home/opc/projects/image_generator
git add app.py tests/test_app_ui.py
git commit -m "feat(app): 모델명 비노출 2탭 스튜디오 UI(이미지/비디오 t2v+i2v)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: 정리 — `local_image_pipeline.py` 삭제, requirements, README 갱신

**Files:**
- Delete: `local_image_pipeline.py`
- Modify: `requirements.txt`
- Modify: `README.md`

**Interfaces:** 없음(정리 태스크)

- [ ] **Step 1: 잔존 참조 확인**

Run: `cd /home/opc/projects/image_generator && grep -rn "local_image_pipeline" app.py tests/ media/ || echo "no refs"`
Expected: `no refs` (Task 6에서 이미 `media` import로 교체됨). 참조가 남아 있으면 먼저 제거.

- [ ] **Step 2: 파일 삭제 + requirements 갱신**

```bash
cd /home/opc/projects/image_generator
git rm local_image_pipeline.py
```

Edit `requirements.txt` — `google-genai>=1.0.0` 줄을 제거하고 주석을 추가:
```
gradio>=5.0.0,<6.0.0
pillow>=10.0.0
fastapi>=0.110.0
uvicorn>=0.27.0
python-docx>=1.1.0
pandas>=2.0.0
openpyxl>=3.1.0
# ComfyUI/LLM HTTP 호출은 stdlib urllib 사용 — 추가 의존 없음.
# 테스트: pytest
```

- [ ] **Step 3: README 갱신**

Replace `README.md` 전체를 ComfyUI 단일 경로 기준으로. 모델명(FLUX/Qwen/Wan/Veo/Gemini/Imagen) 비노출. 다음 골격으로 작성:
```markdown
# Image & Video Studio — 로컬 미디어 생성 스튜디오

로컬 미디어 백엔드(ComfyUI)를 통해 이미지·영상을 생성하는 Gradio 데스크톱/서비스 앱.
사용자는 모델을 고르지 않으며, API 키 입력도 없습니다.

## 기능

### 🎨 이미지 스튜디오
- **텍스트 → 이미지**: 프롬프트만 입력
- **프롬프트 자동 다듬기**(기본 ON): 짧은 아이디어를 고화질 프롬프트로 확장. LLM 백엔드가 없으면
  입력 그대로 사용(자동 폴백)
- **참조 이미지 편집**: 원본 이미지 + 편집 지시로 수정
- **비율**: 1:1 / 9:16 / 16:9 / 3:4 / 4:3

### 🎬 비디오 스튜디오
- **텍스트 → 영상**: 프롬프트로 이미지 생성 후 영상화까지 한 번에
- **이미지 → 영상**: 보유한 이미지를 올려 바로 영상화
- **비율**: 9:16 / 16:9 / 1:1

## 백엔드 설정 (ComfyUI)

앱이 도는 머신(또는 GPU 호스트)에서 ComfyUI를 실행하고 환경변수로 가리킵니다.

```env
COMFYUI_BASE_URL=http://127.0.0.1:8188

# (선택) 워크플로 경로 — 기본값은 media/workflows/*.json
# COMFYUI_TXT2IMG_WORKFLOW=/abs/path/txt2img.json
# COMFYUI_EDIT_WORKFLOW=/abs/path/edit.json
# COMFYUI_I2V_WORKFLOW=/abs/path/i2v.json

# (선택) 프롬프트 자동 다듬기용 OpenAI-호환 LLM. 미설정이면 다듬기 생략(원문 사용).
# IMAGE_PROMPT_LLM_BASE_URL=http://127.0.0.1:11434/v1
# IMAGE_PROMPT_LLM_MODEL=<model-name>

# (선택) 제한 해제 편집 모드는 이 서버 플래그가 켜진 경우에만 실효.
# IMAGE_NSFW_ENABLED=0
```

## 실행

```bash
pip install -r requirements.txt
python launcher.py        # 또는: python app.py  (APP_PORT 로 포트 지정)
```

## 테스트

```bash
python3 -m pytest        # media/ 단위 테스트(네트워크 불필요)
```

## 구조

- `app.py` — Gradio UI + 와이어링
- `media/` — 미디어 파이프라인 패키지(Gradio 비의존)
  - `backend.py` 설정 · `comfyui.py` 백엔드 클라이언트 · `llm.py` 프롬프트 다듬기 ·
    `pipeline.py` 다단계 파이프라인 · `workflows/` 워크플로 템플릿
```

- [ ] **Step 4: 최종 회귀 + 모델명 누출 전역 점검**

Run: `cd /home/opc/projects/image_generator && python3 -m pytest tests/ -v`
Expected: 전부 PASS

Run: `cd /home/opc/projects/image_generator && grep -rniE "flux|qwen|veo|gemini|imagen|comfyui|\bwan\b" app.py README.md | grep -viE "COMFYUI_|comfyui\)" || echo "사용자 표면 누출 없음"`
Expected: `사용자 표면 누출 없음` (env 변수명 `COMFYUI_*` 와 README의 백엔드 설정 안내는 운영자 대상이라 허용). app.py엔 어떤 매치도 없어야 함.

- [ ] **Step 5: 커밋**

```bash
cd /home/opc/projects/image_generator
git add -A
git commit -m "chore: local_image_pipeline 제거 · requirements/README 갱신

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (계획 작성자 자체 점검 결과)

**1. Spec coverage:**
- 모델명 비노출 → Task 7(UI 중립 텍스트 + 누출 테스트), Task 8(README/전역 점검). ✅
- 이미지 다단계(expand→txt2img→edit) → Task 5. ✅
- 비디오 t2v+i2v → Task 5(make_video 분기), Task 7(모드 라디오). ✅
- 프롬프트 확장 기본 ON + 폴백 → Task 3(폴백), Task 7(기본 ON 체크박스). ✅
- 죽은 코드 제거 + README → Task 6(제거), Task 8(README). ✅
- jobs 미이식/Gradio 제너레이터 → Task 6-7(generator yield). ✅
- NSFW 게이팅 → Task 1(resolve_image_mode), Task 5(weight), Task 6(handler). ✅
- 워크플로 중립 파일명 → Task 4. ✅
- 신규 외부 의존 금지(urllib) → Task 2, Task 8(requirements). ✅
- 백엔드 부재 내성 → Task 6(_friendly_error 테스트). ✅

**2. Placeholder scan:** 모든 코드 스텝에 실제 코드 포함. "TBD/적절히 처리" 없음. ✅

**3. Type consistency:** `fetch_media`(comfyui)·`first_media_ref`·`make_image/make_video` 반환 dict 키(image/video/mime/base_image/prompt_used)가 Task 5 정의와 Task 6 핸들러 소비에서 일치. `on_stage` 단계 문자열(expand/txt2img/edit/img2video/done)이 `STAGE_LABELS` 키와 일치. ✅
- 주의: Task 2의 `fetch_media`(이름)는 ArcAI.ve의 `fetch_image`와 다름 — 비디오도 가져오므로 의도적으로 `fetch_media`로 통일. Task 5가 이 이름으로 호출하므로 정합.

## 범위 메모
- 배치 N장, auto-extend, 채팅형 히스토리, 외부 REST 잡 API는 의도적으로 제외(설계 §8 YAGNI).
- ComfyUI/LLM 실연동(실제 GPU 생성)은 이 호스트에 백엔드가 없어 수동 검증 불가 — 단위 테스트(목킹)와 UI 기동 스모크로 대체. 실백엔드 통합 검증은 사용자가 ComfyUI 환경에서 수행.
