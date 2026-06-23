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
