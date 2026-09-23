import os

import app  # gradio 는 실제 설치돼 있음(서비스가 사용). import 시 build_ui 는 호출되지 않음.


def test_generate_images_streams_status_and_path(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))

    def _fake_make_image(**kw):
        assert kw["mode"] == "sfw"          # 토글을 안 켜면 항상 SFW
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


def test_app_exposes_no_video_handlers():
    """영상 기능 전면 제거(2026-07-09) — 재도입 방지 회귀 테스트."""
    for gone in ("generate_video", "concat_videos"):
        assert not hasattr(app, gone), gone


def test_generate_and_edit_cannot_run_at_the_same_time(monkeypatch, tmp_path):
    """생성/편집은 서로 다른 체크포인트를 VRAM 에 올린다 — 동시에 돌면 OOM.
    한쪽이 GPU 락을 쥐고 있으면 다른 쪽은 즉시 거절돼야 한다(대기 아님)."""
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
    target = tmp_path / "t.png"
    target.write_bytes(b"PNG")

    assert app._GPU_LOCK.acquire(blocking=False)   # 다른 작업이 점유 중인 상황 재현
    try:
        g_status, g_out = list(app.generate_images("a cat", 1, "1:1", True))[-1]
        e_status, e_out = list(app.edit_images(str(target), None, "분위기 이식", "더 선명하게"))[-1]
    finally:
        app._GPU_LOCK.release()
    assert g_out is None and e_out is None
    assert g_status == app.BUSY_MSG and e_status == app.BUSY_MSG


def test_gpu_lock_is_released_after_generate_completes(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(app.pipeline, "make_image",
                        lambda **k: {"image": b"PNGDATA", "prompt_used": "x"})
    list(app.generate_images("a cat", 1, "1:1", True))
    assert app._GPU_LOCK.acquire(blocking=False), "정상 종료 후 GPU 락이 안 풀렸다"
    app._GPU_LOCK.release()


def test_gpu_lock_is_released_after_generate_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))

    def _boom(**k):
        raise OSError("Connection refused")

    monkeypatch.setattr(app.pipeline, "make_image", _boom)
    list(app.generate_images("a cat", 1, "1:1", True))
    assert app._GPU_LOCK.acquire(blocking=False), "실패 후 GPU 락이 안 풀렸다"
    app._GPU_LOCK.release()


def test_gpu_lock_is_held_until_worker_finishes_when_generator_is_cancelled(monkeypatch, tmp_path):
    """⏹️ 중지는 제너레이터만 닫는다 — 백엔드 작업은 계속 돈다.
    워커가 살아있는 동안 락을 풀면 다음 작업이 겹쳐 붙어 OOM 이다."""
    import threading as _th
    import time as _time
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
    release = _th.Event()

    def _slow(**k):
        release.wait(5)
        return {"image": b"PNGDATA", "prompt_used": "x"}

    monkeypatch.setattr(app.pipeline, "make_image", _slow)
    gen = app.generate_images("a cat", 1, "1:1", True)
    next(gen)                                    # 워커 시작
    gen.close()                                  # ⏹️ 중지 == GeneratorExit
    assert not app._GPU_LOCK.acquire(blocking=False), "워커가 도는 중인데 락이 풀렸다"
    release.set()
    for _ in range(100):                         # 워커 종료 후에는 풀려야 한다
        if app._GPU_LOCK.acquire(blocking=False):
            app._GPU_LOCK.release()
            return
        _time.sleep(0.05)
    raise AssertionError("워커 종료 후에도 GPU 락이 안 풀렸다")


def _capture_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
    seen = {}

    def _fake(**kw):
        seen["mode"] = kw["mode"]
        return {"image": b"PNGDATA", "prompt_used": "x"}

    monkeypatch.setattr(app.pipeline, "make_image", _fake)
    return seen


def test_unrestricted_toggle_is_honored_when_server_flag_on(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAGE_NSFW_ENABLED", "1")
    seen = _capture_mode(monkeypatch, tmp_path)
    outs = list(app.generate_images("a nude woman", 1, "1:1", True, True))
    assert seen["mode"] == "uncensored"          # 차단어 게이트는 기본 모드에만 걸린다
    assert outs[-1][1]


def test_unrestricted_toggle_is_downgraded_when_server_flag_off(monkeypatch, tmp_path):
    monkeypatch.delenv("IMAGE_NSFW_ENABLED", raising=False)
    seen = _capture_mode(monkeypatch, tmp_path)
    outs = list(app.generate_images("a nude woman", 1, "1:1", True, True))
    assert "mode" not in seen                    # sfw 로 강등 → 차단어 게이트에 걸려 호출 자체가 없다
    assert outs[-1][1] is None
    list(app.generate_images("a cat", 1, "1:1", True, True))
    assert seen["mode"] == "sfw"


