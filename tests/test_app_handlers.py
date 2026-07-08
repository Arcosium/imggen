import os

import app  # gradio 는 실제 설치돼 있음(서비스가 사용). import 시 build_ui 는 호출되지 않음.


def test_generate_images_streams_status_and_path(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))

    def _fake_make_image(**kw):
        assert kw["mode"] == "sfw"          # 스튜디오는 항상 SFW
        kw["on_stage"]("txt2img")
        kw["on_stage"]("done")
        return {"image": b"PNGDATA", "prompt_used": "x"}

    monkeypatch.setattr(app.pipeline, "make_image", _fake_make_image)
    outs = list(app.generate_images("a cat", 1, "1:1", True))
    final_status, final_gallery = outs[-1]
    assert final_gallery and os.path.exists(final_gallery[0])
    assert open(final_gallery[0], "rb").read() == b"PNGDATA"
    assert "완료" in final_status or "✅" in final_status


def test_generate_images_handles_backend_error_gracefully(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))

    def _boom(**k):
        raise OSError("Connection refused to 127.0.0.1:8188")

    monkeypatch.setattr(app.pipeline, "make_image", _boom)
    outs = list(app.generate_images("a cat", 1, "1:1", True))
    final_status, final_gallery = outs[-1]
    assert final_gallery is None
    assert "127.0.0.1" not in final_status      # 내부 세부정보 비노출
    assert "백엔드" in final_status


def test_generate_images_blocks_nsfw_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
    called = {"n": 0}

    def _should_not_run(**k):
        called["n"] += 1
        return {"image": b"X", "prompt_used": "x"}

    monkeypatch.setattr(app.pipeline, "make_image", _should_not_run)
    outs = list(app.generate_images("a nude woman", 1, "1:1", True))
    final_status, final_gallery = outs[-1]
    assert final_gallery is None
    assert called["n"] == 0                     # 파이프라인 호출 자체가 차단됨
    assert "🚫" in final_status or "부적절" in final_status


def test_edit_images_blocks_nsfw_instruction(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
    target = tmp_path / "t.png"
    target.write_bytes(b"PNG")
    called = {"n": 0}

    def _should_not_run(*a, **k):
        called["n"] += 1
        return b"X"

    monkeypatch.setattr(app.pipeline, "edit_image", _should_not_run)
    monkeypatch.setattr(app.pipeline, "edit_image_ref", _should_not_run)
    outs = list(app.edit_images(str(target), None, "분위기 이식", "make her topless"))
    final_status, final_out = outs[-1]
    assert final_out is None
    assert called["n"] == 0
    assert "🚫" in final_status or "부적절" in final_status


def test_generate_video_image_mode_requires_input(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
    # (vmode, prompt, input_image, input_video, aspect, edit_instr, motion_only, expand_on)
    outs = list(app.generate_video("이미지→영상", "move it", None, None, "9:16", "", False, True))
    final_status, final_path = outs[-1]
    assert final_path is None
    assert "이미지" in final_status


def test_generate_video_blocks_nsfw_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
    called = {"n": 0}

    def _should_not_run(**k):
        called["n"] += 1
        return {"video": b"X", "mime": "video/mp4"}

    monkeypatch.setattr(app.pipeline, "make_video", _should_not_run)
    outs = list(app.generate_video("텍스트→영상", "explicit porn clip", None, None, "9:16", "", False, True))
    final_status, final_path = outs[-1]
    assert final_path is None
    assert called["n"] == 0
    assert "🚫" in final_status or "부적절" in final_status
