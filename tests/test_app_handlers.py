import os
import time
from types import SimpleNamespace

import pytest

import app  # gradio 는 실제 설치돼 있음(서비스가 사용). import 시 build_ui 는 호출되지 않음.


@pytest.fixture(autouse=True)
def _fresh_jobs(monkeypatch):
    monkeypatch.setattr(app, "_JOBS", {})


def _req(user="u1"):
    return SimpleNamespace(username=user)


def _wait(kind, user="u1"):
    """작업이 시작됐으면 끝날 때까지 기다린 뒤 (상태, 결과) — 시작 안 됐으면 None."""
    job = app._JOBS.get((user, kind))
    if job is None:
        return None
    for _ in range(200):
        if job["done"]:
            return app._job_view(job)
        time.sleep(0.02)
    raise AssertionError("작업이 끝나지 않았다")


def _gen(*args, user="u1"):
    status, result, _ = app.generate_images(*args, request=_req(user))
    return _wait("gen", user) or (status, result)


def _edit(*args, user="u1"):
    status, result, _ = app.edit_images(*args, request=_req(user))
    return _wait("edit", user) or (status, result)


def test_generate_images_streams_status_and_path(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))

    def _fake_make_image(**kw):
        assert kw["mode"] == "sfw"          # 토글을 안 켜면 항상 SFW
        kw["on_stage"]("txt2img")
        kw["on_stage"]("done")
        return {"image": b"PNGDATA", "prompt_used": "x"}

    monkeypatch.setattr(app.pipeline, "make_image", _fake_make_image)
    final_status, final_gallery = _gen("a cat", 1, "1:1", True)
    assert final_gallery and os.path.exists(final_gallery[0])
    assert open(final_gallery[0], "rb").read() == b"PNGDATA"
    assert "완료" in final_status or "✅" in final_status


def test_generate_images_handles_backend_error_gracefully(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))

    def _boom(**k):
        raise OSError("Connection refused to 127.0.0.1:8188")

    monkeypatch.setattr(app.pipeline, "make_image", _boom)
    final_status, final_gallery = _gen("a cat", 1, "1:1", True)
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
    final_status, final_gallery = _gen("a nude woman", 1, "1:1", True)
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
    final_status, final_out = _edit(str(target), None, "분위기 이식", "make her topless")
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
        g_status, _ = _gen("a cat", 1, "1:1", True)
        e_status, _ = _edit(str(target), None, "분위기 이식", "더 선명하게")
    finally:
        app._GPU_LOCK.release()
    assert g_status == app.BUSY_MSG and e_status == app.BUSY_MSG
    assert app._JOBS == {}                       # 거절된 쪽은 작업을 만들지 않는다


def test_gpu_lock_is_released_after_generate_completes(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(app.pipeline, "make_image",
                        lambda **k: {"image": b"PNGDATA", "prompt_used": "x"})
    _gen("a cat", 1, "1:1", True)
    assert app._GPU_LOCK.acquire(blocking=False), "정상 종료 후 GPU 락이 안 풀렸다"
    app._GPU_LOCK.release()


def test_gpu_lock_is_released_after_generate_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))

    def _boom(**k):
        raise OSError("Connection refused")

    monkeypatch.setattr(app.pipeline, "make_image", _boom)
    _gen("a cat", 1, "1:1", True)
    assert app._GPU_LOCK.acquire(blocking=False), "실패 후 GPU 락이 안 풀렸다"
    app._GPU_LOCK.release()


def test_job_survives_disconnect_and_is_restored_for_same_account(monkeypatch, tmp_path):
    """앱 전환·화면 잠금으로 연결이 끊겨도(=이벤트가 끝나도) 작업은 서버에서 N장을 끝까지 돌고,
    같은 계정이 다시 열면(poll_jobs) 진행·결과가 복원된다. 다른 계정에는 보이지 않는다."""
    import threading as _th
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
    gate = _th.Event()

    def _slow(**k):
        gate.wait(5)
        return {"image": b"PNGDATA", "prompt_used": "x"}

    monkeypatch.setattr(app.pipeline, "make_image", _slow)
    status, _, timer = app.generate_images("a cat", 2, "1:1", True, request=_req("alice"))
    assert "경과" in status                      # 클릭 이벤트는 바로 끝난다 — 연결과 무관

    g_status, g_gal, e_status, e_out, seen, timer = app.poll_jobs({}, request=_req("alice"))
    assert "(1/2)" in g_status and timer.active is True
    assert app.poll_jobs({}, request=_req("bob"))[0] == app.gr.skip()   # 남의 작업은 안 보인다

    gate.set()
    final_status, final_gallery = _wait("gen", "alice")
    assert "완료 (2장" in final_status and len(final_gallery) == 2

    g_status, g_gal, _, _, seen, timer = app.poll_jobs({}, request=_req("alice"))   # 새로 연 화면
    assert g_gal == final_gallery and timer.active is False
    again = app.poll_jobs(seen, request=_req("alice"))                              # 바뀐 게 없으면
    assert again[1] == app.gr.skip()                                                 # 갤러리를 다시 안 보낸다


def test_stop_finishes_current_image_then_releases_gpu(monkeypatch, tmp_path):
    """중지는 백엔드에 넘긴 장까지 마치고 다음 장부터 멈춘다. 그 장이 도는 동안엔 락을 쥐고 있어야
    한다 — 풀면 다음 작업이 겹쳐 붙어 OOM 이다."""
    import threading as _th
    monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
    gate, calls = _th.Event(), []

    def _slow(**k):
        calls.append(1)
        gate.wait(5)
        return {"image": b"PNGDATA", "prompt_used": "x"}

    monkeypatch.setattr(app.pipeline, "make_image", _slow)
    app.generate_images("a cat", 4, "1:1", True, request=_req())
    app.stop_job("gen")(request=_req())
    assert not app._GPU_LOCK.acquire(blocking=False), "워커가 도는 중인데 락이 풀렸다"
    gate.set()
    final_status, final_gallery = _wait("gen")
    assert len(calls) == 1 and len(final_gallery) == 1 and final_status.startswith("중지")
    assert app._GPU_LOCK.acquire(blocking=False), "워커 종료 후에도 GPU 락이 안 풀렸다"
    app._GPU_LOCK.release()


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
    _, result = _gen("a nude woman", 1, "1:1", True, True)
    assert seen["mode"] == "uncensored"          # 차단어 게이트는 기본 모드에만 걸린다
    assert result


def test_unrestricted_toggle_is_downgraded_when_server_flag_off(monkeypatch, tmp_path):
    monkeypatch.delenv("IMAGE_NSFW_ENABLED", raising=False)
    seen = _capture_mode(monkeypatch, tmp_path)
    _, result = _gen("a nude woman", 1, "1:1", True, True)
    assert "mode" not in seen                    # sfw 로 강등 → 차단어 게이트에 걸려 호출 자체가 없다
    assert result is None
    _gen("a cat", 1, "1:1", True, True)
    assert seen["mode"] == "sfw"


