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
