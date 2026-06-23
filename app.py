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
from auth import store
import html as _html
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


MANUAL_DOCX = os.path.join(BASE_DIR, "사용설명서.docx")
_manual_cache = {"html": None}


def render_manual_html():
    """사용설명서 .docx 를 HTML 본문 조각으로 변환(탭 내 gr.HTML 용). 캐시."""
    if _manual_cache["html"] is not None:
        return _manual_cache["html"]
    if not os.path.exists(MANUAL_DOCX):
        html = "<p>사용설명서 파일을 찾을 수 없습니다.</p>"
    else:
        try:
            import mammoth
            with open(MANUAL_DOCX, "rb") as f:
                html = mammoth.convert_to_html(f).value
        except Exception:
            try:
                from docx import Document
                doc = Document(MANUAL_DOCX)
                html = "".join(
                    "<p>%s</p>" % (p.text or "").replace("<", "&lt;").replace(">", "&gt;")
                    for p in doc.paragraphs)
            except Exception as e2:
                html = "<pre>사용설명서 변환 실패: %s</pre>" % e2
    _manual_cache["html"] = "<div style='max-width:880px;line-height:1.7'>%s</div>" % html
    return _manual_cache["html"]


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


# =============== [ 인증: 로그인 / 가입 ] ===============
AUTH_MESSAGE = ('승인된 계정만 입장할 수 있습니다. 계정이 없다면 '
                '<a href="signup" style="color:#7ec8ff">가입 신청</a> 후 관리자 승인을 기다려 주세요.')


def authenticate(username, password):
    """Gradio 로그인 콜백 — 승인된 계정만 통과, 5회 실패 시 잠금."""
    return store.check_login(username, password)


def signup_submit(username, password):
    """가입 신청 처리(테스트 가능 순수 로직). (ok, msg) 반환."""
    return store.create_pending(username, password)


def _admin_view(actor):
    """(allowed, pending, msg) — actor가 관리자일 때만 대기 목록 노출."""
    if not store.is_admin(actor):
        return False, [], "관리자만 사용할 수 있습니다."
    pending = store.list_pending()
    return True, pending, ("대기 중 %d명" % len(pending)) if pending else "대기 중인 신청이 없습니다."


def admin_approve_action(username, actor):
    if not store.is_admin(actor):
        return False, "관리자만 사용할 수 있습니다."
    if not username:
        return False, "승인할 아이디를 선택하세요."
    store.approve(username)
    return True, "승인 완료: %s" % username


def admin_reject_action(username, actor):
    if not store.is_admin(actor):
        return False, "관리자만 사용할 수 있습니다."
    if not username:
        return False, "거절할 아이디를 선택하세요."
    store.reject(username)
    return True, "거절 완료: %s" % username


def _signup_page_html():
    return """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>가입 신청</title>
<style>
 body{background:#121212;color:#eee;font-family:'Pretendard','Apple SD Gothic Neo',sans-serif;
      display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0;}
 .card{background:#1e1e1e;border:1px solid #333;border-radius:14px;padding:32px;width:320px;}
 h1{font-size:1.3rem;margin:0 0 6px;} p{color:#aaa;font-size:.9rem;margin:0 0 18px;}
 label{display:block;font-size:.85rem;margin:12px 0 4px;}
 input{width:100%;box-sizing:border-box;padding:10px;border-radius:8px;border:1px solid #444;
       background:#2a2a2a;color:#fff;}
 button{margin-top:18px;width:100%;padding:11px;border:0;border-radius:8px;background:#ffd966;
        color:#000;font-weight:700;cursor:pointer;}
 a{color:#7ec8ff;}
</style></head><body>
<form class="card" method="post" action="signup">
 <h1>가입 신청</h1>
 <p>관리자 승인 후 로그인할 수 있습니다.</p>
 <label>아이디</label><input name="username" autocomplete="username" required>
 <label>비밀번호</label><input name="password" type="password" autocomplete="new-password" required>
 <button type="submit">가입 신청</button>
 <p style="margin-top:16px"><a href="./">← 로그인으로</a></p>
</form></body></html>"""


def _signup_result_html(ok, msg):
    color = "#8fe388" if ok else "#ff8f8f"
    return ("""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<title>가입 신청</title><style>
 body{background:#121212;color:#eee;font-family:'Pretendard',sans-serif;display:flex;min-height:100vh;
      align-items:center;justify-content:center;margin:0;}
 .card{background:#1e1e1e;border:1px solid #333;border-radius:14px;padding:32px;width:320px;text-align:center;}
 a{color:#7ec8ff;}
</style></head><body><div class="card">
 <p style="color:%s;font-size:1rem">%s</p>
 <p><a href="./">로그인으로</a> · <a href="signup">다시 신청</a></p>
</div></body></html>""" % (color, _html.escape(msg)))


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


CSS = """
body.dark { font-family: 'Pretendard', sans-serif; background-color: #121212 !important; color: #fff !important; }
#result-img, #result-vid { border-radius: 12px; background:#1e1e1e !important; border:1px solid #333; }
#sidebar-img, #sidebar-vid { background:#181818 !important; padding:18px; border-radius:12px; border:1px solid #333; }
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
                gr.Markdown("Made by Hyunho Kim · ")
            with gr.Column(scale=1, min_width=140):
                gr.Markdown("")

        with gr.Tabs():
            # ---- 이미지 스튜디오 ----
            with gr.Tab("🎨 이미지 스튜디오"):
                with gr.Row():
                    with gr.Column(scale=2, elem_id="sidebar-img"):
                        img_prompt = gr.Textbox(label="프롬프트", lines=4,
                                                placeholder="만들고 싶은 이미지를 자유롭게 적어 주세요.")
                        img_aspect = gr.Dropdown(choices=aspects, value="1:1", label="비율")
                        img_ref = gr.File(file_count="multiple", file_types=["image"],
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
                    with gr.Column(scale=2, elem_id="sidebar-vid"):
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

            # ---- 관리자 승인 ----
            with gr.Tab("🔐 관리자"):
                gr.Markdown("관리자만 사용할 수 있습니다. 가입 신청을 승인/거절합니다.")
                adm_status = gr.Textbox(label="상태", interactive=False)
                adm_pending = gr.Dropdown(choices=[], label="대기 중 신청", interactive=True)
                with gr.Row():
                    adm_refresh = gr.Button("🔄 새로고침")
                    adm_approve = gr.Button("✅ 승인", variant="primary")
                    adm_reject = gr.Button("⛔ 거절", variant="stop")

                def _adm_refresh(request: gr.Request):
                    actor = getattr(request, "username", None)
                    allowed, pending, msg = _admin_view(actor)
                    return gr.update(choices=pending, value=(pending[0] if pending else None)), msg

                def _adm_approve(selected, request: gr.Request):
                    actor = getattr(request, "username", None)
                    _, msg = admin_approve_action(selected, actor)
                    allowed, pending, _ = _admin_view(actor)
                    return gr.update(choices=pending, value=(pending[0] if pending else None)), msg

                def _adm_reject(selected, request: gr.Request):
                    actor = getattr(request, "username", None)
                    _, msg = admin_reject_action(selected, actor)
                    allowed, pending, _ = _admin_view(actor)
                    return gr.update(choices=pending, value=(pending[0] if pending else None)), msg

                adm_refresh.click(fn=_adm_refresh, inputs=None,
                                  outputs=[adm_pending, adm_status], api_name=False)
                adm_approve.click(fn=_adm_approve, inputs=[adm_pending],
                                  outputs=[adm_pending, adm_status], api_name=False)
                adm_reject.click(fn=_adm_reject, inputs=[adm_pending],
                                 outputs=[adm_pending, adm_status], api_name=False)

            # ---- 사용설명서 ----
            with gr.Tab("📖 사용설명서"):
                gr.HTML(render_manual_html())
                gr.DownloadButton("⬇️ 원본(.docx) 다운로드", value=MANUAL_DOCX, variant="secondary")

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

    from fastapi import Form
    from fastapi.responses import HTMLResponse

    store.seed_admin()

    @app_api.get("/signup", response_class=HTMLResponse)
    def signup_page():
        return HTMLResponse(_signup_page_html())

    @app_api.post("/signup", response_class=HTMLResponse)
    def signup_post(username: str = Form(""), password: str = Form("")):
        ok, msg = signup_submit(username, password)
        return HTMLResponse(_signup_result_html(ok, msg))

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
    app_api = gr.mount_gradio_app(app_api, demo, path="/", root_path=root_path,
                                  auth=authenticate, auth_message=AUTH_MESSAGE)
    uvicorn.run(app_api, host="0.0.0.0", port=PORT)
