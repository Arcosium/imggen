import os
import signal
import time
from datetime import datetime
from zoneinfo import ZoneInfo


def _patch_gradio_client():
    try:
        from gradio_client import utils as gc_utils
    except ImportError:
        return

    if hasattr(gc_utils, "get_type"):
        _orig_gt = gc_utils.get_type

        def _safe_get_type(schema):
            if not isinstance(schema, dict):
                return "Any"
            try:
                return _orig_gt(schema)
            except Exception:
                return "Any"

        gc_utils.get_type = _safe_get_type

    if hasattr(gc_utils, "_json_schema_to_python_type"):
        _orig_j = gc_utils._json_schema_to_python_type

        def _safe_json(schema, defs=None):
            if not isinstance(schema, dict):
                return "Any"
            try:
                return _orig_j(schema, defs)
            except Exception:
                return "Any"

        gc_utils._json_schema_to_python_type = _safe_json

    if hasattr(gc_utils, "json_schema_to_python_type"):
        _orig_j2 = gc_utils.json_schema_to_python_type

        def _safe_json2(schema):
            try:
                return _orig_j2(schema)
            except Exception:
                return "Any"

        gc_utils.json_schema_to_python_type = _safe_json2


_patch_gradio_client()

import gradio as gr
from media import backend, pipeline
import logging
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


def generate_image(prompt, ref_files, aspect, expand_on, edit_instr, nsfw):
    """이미지 생성 제너레이터: (상태문구, 이미지경로) 를 단계별로 yield."""
    if not (prompt and prompt.strip()) and not (edit_instr and edit_instr.strip()):
        yield "프롬프트를 입력해 주세요.", None
        return

    source_path = None
    if ref_files:
        for f in ref_files:
            if str(f).lower().rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "webp"):
                source_path = f
                break

    stages = {"label": "⏳ 시작하는 중..."}

    def _on_stage(s):
        stages["label"] = STAGE_LABELS.get(s, stages["label"])

    def _work():
        mode = backend.resolve_image_mode("uncensored" if nsfw else "sfw")
        if source_path:
            _on_stage("edit")
            with open(source_path, "rb") as f:
                img_bytes = f.read()
            edited = pipeline.edit_image(img_bytes, edit_instr or prompt, mode=mode)
            return _save_bytes(edited, "png")
        res = pipeline.make_image(
            idea=prompt, prompt=None, aspect=aspect, mode=mode,
            edit_instructions=(edit_instr or None), expand=bool(expand_on),
            on_stage=_on_stage,
        )
        return _save_bytes(res["image"], "png")

    box = {}

    def _runner():
        try:
            box["path"] = _work()
        except Exception as exc:  # noqa: BLE001
            box["err"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    yield stages["label"], None
    while t.is_alive():
        t.join(timeout=0.5)
        yield stages["label"], None

    if "err" in box:
        logging.getLogger("studio").warning("generate_image failed: %s", box["err"])
        yield _friendly_error(box["err"]), None
        return
    yield "✅ 완료", box["path"]


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

    stages = {"label": "⏳ 시작하는 중..."}

    def _on_stage(s):
        stages["label"] = STAGE_LABELS.get(s, stages["label"])

    def _work():
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
        return _save_bytes(res["video"], ext)

    box = {}

    def _runner():
        try:
            box["path"] = _work()
        except Exception as exc:  # noqa: BLE001
            box["err"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    yield stages["label"], None
    while t.is_alive():
        t.join(timeout=0.5)
        yield stages["label"], None

    if "err" in box:
        logging.getLogger("studio").warning("generate_video failed: %s", box["err"])
        yield _friendly_error(box["err"]), None
        return
    yield "✅ 완료", box["path"]


def build_ui():
    with gr.Blocks() as demo:
        gr.Markdown("UI 구성 예정")
    return demo


def _resolve_port():
    import socket
    env_port = os.environ.get("APP_PORT") or os.environ.get("GRADIO_SERVER_PORT") or os.environ.get("PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass
    for port in range(7861, 7899):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    return 7860


if __name__ == "__main__":
    from fastapi import FastAPI
    import uvicorn

    demo = build_ui()
    app_api = FastAPI()
    PORT = _resolve_port()

    @app_api.post("/shutdown")
    def shutdown():
        print(f"💡 브라우저 연결 종료가 감지되었습니다. 서버 포트({PORT})를 안전하게 해제하고 종료합니다.")
        os.kill(os.getpid(), signal.SIGINT)
        return {"status": "shutting down"}

    from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse

    MANUAL_DOCX = os.path.join(BASE_DIR, "사용설명서.docx")
    _manual_cache = {"html": None}

    def _render_manual_html() -> str:
        if _manual_cache["html"] is not None:
            return _manual_cache["html"]
        if not os.path.exists(MANUAL_DOCX):
            return "<h2>사용설명서 파일을 찾을 수 없습니다.</h2>"
        try:
            import mammoth
            with open(MANUAL_DOCX, "rb") as f:
                body = mammoth.convert_to_html(f).value
        except Exception as e:
            try:
                from docx import Document
                doc = Document(MANUAL_DOCX)
                paras = "".join(f"<p>{(p.text or '').replace('<','&lt;').replace('>','&gt;')}</p>" for p in doc.paragraphs)
                body = paras or f"<p>변환 오류: {e}</p>"
            except Exception as e2:
                body = f"<pre>사용설명서 변환 실패: {e2}</pre>"

        page = f"""<!DOCTYPE html>
<html lang=\"ko\"><head><meta charset=\"utf-8\">
<title>📖 Image &amp; Video Laboratory 사용설명서</title>
<style>
  body {{ background:#1a1a1a; color:#eee; font-family:'Pretendard','Apple SD Gothic Neo','맑은 고딕',sans-serif;
         max-width:880px; margin:0 auto; padding:32px 24px 80px; line-height:1.7; }}
  h1, h2, h3 {{ color:#ffd966; border-bottom:1px solid #444; padding-bottom:6px; margin-top:1.6em; }}
  h1 {{ font-size:1.8rem; }} h2 {{ font-size:1.4rem; }} h3 {{ font-size:1.15rem; }}
  p, li {{ font-size:15px; }}
  code, pre {{ background:#2a2a2a; color:#fae; padding:2px 6px; border-radius:4px; }}
  pre {{ padding:12px; overflow-x:auto; }}
  a {{ color:#7ec8ff; }}
  table {{ border-collapse:collapse; margin:10px 0; }}
  td, th {{ border:1px solid #555; padding:6px 10px; }}
  img {{ max-width:100%; height:auto; }}
  .download-btn {{ position:fixed; top:14px; right:18px; background:#ffd966; color:#000;
                  padding:8px 14px; border-radius:8px; font-weight:600; text-decoration:none;
                  box-shadow:0 2px 8px rgba(0,0,0,.4); }}
  .download-btn:hover {{ background:#ffe7a0; }}
</style></head><body>
<a class=\"download-btn\" href=\"manual/download\">⬇️ 원본(.docx) 다운로드</a>
{body}
</body></html>"""
        _manual_cache["html"] = page
        return page

    @app_api.get("/manual", response_class=HTMLResponse)
    def manual_page():
        return HTMLResponse(_render_manual_html())

    @app_api.get("/manual/download")
    def manual_download():
        if not os.path.exists(MANUAL_DOCX):
            return PlainTextResponse("사용설명서 파일이 없습니다.", status_code=404)
        return FileResponse(
            MANUAL_DOCX,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename="사용설명서.docx",
        )

    launched_by_parent = bool(
        os.environ.get("LAUNCHED_BY_SCRIPT")
        or os.environ.get("APP_PORT")
        or os.environ.get("GRADIO_SERVER_PORT")
    )

    if launched_by_parent:
        @app_api.on_event("startup")
        async def _signal_ready():
            flag = os.path.join(BASE_DIR, "server_ready.flag")
            try:
                with open(flag, "w") as f:
                    f.write("1")
                print(f"[ready] flag written: {flag}", flush=True)
            except Exception as e:
                print(f"[ready] failed to write flag: {e}", flush=True)
    else:
        def open_browser():
            time.sleep(3)
            webbrowser.open(f"http://127.0.0.1:{PORT}")
        threading.Thread(target=open_browser, daemon=True).start()

    # mysite의 nginx는 /p/<port>/ 로 들어오는 요청의 프리픽스를 떼고 proxy_pass 하므로,
    # Gradio가 자산 URL을 정확히 생성하려면 root_path 를 /p/<port> 로 알려줘야 한다.
    root_path = os.environ.get("GRADIO_ROOT_PATH")
    if root_path is None and launched_by_parent:
        root_path = f"/p/{PORT}"

    print(f"[Image Generator] Starting on port {PORT} (root_path={root_path or '/'})", flush=True)
    app_api = gr.mount_gradio_app(app_api, demo, path="/", root_path=root_path)
    uvicorn.run(app_api, host="0.0.0.0", port=PORT)
