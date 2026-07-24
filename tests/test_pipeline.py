from media import pipeline


def _stub_comfyui(monkeypatch, *, image=b"IMG"):
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
    monkeypatch.setattr(pipeline.comfyui, "fetch_media", lambda url, ref: image)

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
    assert stages == ["expand", "txt2img", "edit", "done"]


def test_make_image_expand_off_uses_raw_prompt(monkeypatch):
    _stub_comfyui(monkeypatch)
    res = pipeline.make_image(prompt="raw prompt", expand=False)
    assert res["prompt_used"] == "raw prompt"


def test_pipeline_exposes_no_video_api():
    """영상 기능 전면 제거(2026-07-09) — 재도입 방지 회귀 테스트."""
    for gone in ("img2video", "make_video", "_video_first_frame"):
        assert not hasattr(pipeline, gone), gone
