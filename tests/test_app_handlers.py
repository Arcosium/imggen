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
