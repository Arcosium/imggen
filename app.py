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


# 공개 스튜디오는 전체이용가(SFW) 전용 — 성적/노출 요청은 생성 전에 차단한다.
SFW_REFUSAL = "🚫 부적절(성적·노출) 요청은 생성할 수 없습니다. 이 스튜디오는 전체이용가 콘텐츠만 제공합니다."


# =============== [ 인증: 로그인 / 가입 ] ===============
# auth_message 는 로그인 페이지에 HTML 그대로 렌더된다(Gradio 기본 로그인 화면은 gr.Blocks 의
# theme/css 가 닿지 않으므로, 여기 <style> 을 끼워 로그인 화면까지 다크로 통일한다).
AUTH_MESSAGE = (
    '<style>'
    'body,gradio-app,.gradio-container,.main,.app{background:#121212 !important;color:#ececec !important;}'
    '.gradio-container input,gradio-app input{background:#1c1c1c !important;color:#fff !important;'
    'border:1px solid #3a3a3a !important;}'
    'gradio-app button{background:#7c3aed !important;color:#fff !important;border:0 !important;}'
    'gradio-app .form,gradio-app .block,gradio-app fieldset{background:#181818 !important;'
    'border-color:#333 !important;}'
    'gradio-app label,gradio-app span,gradio-app h1,gradio-app h2,gradio-app p{color:#ececec !important;}'
    '</style>'
    '승인된 계정만 입장할 수 있습니다. 계정이 없다면 '
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


def generate_images(prompt, count, aspect, expand_on):
    """이미지 생성(텍스트→이미지, N장). (상태문구, 갤러리리스트) 를 단계별로 yield."""
    if not (prompt and prompt.strip()):
        yield "프롬프트를 입력해 주세요.", None
        return
    if backend.sfw_violation(prompt):
        yield SFW_REFUSAL, None
        return
    try:
        n = max(1, min(int(count or 1), 8))
    except (TypeError, ValueError):
        n = 1
    stages = {"label": "⏳ 시작하는 중..."}

    def _on_stage(s):
        stages["label"] = STAGE_LABELS.get(s, stages["label"])

    mode = "sfw"
    results = []
    for i in range(n):
        box = {}

        def _runner():
            try:
                res = pipeline.make_image(idea=prompt, prompt=None, aspect=aspect, mode=mode,
                                          expand=bool(expand_on), on_stage=_on_stage)
                box["path"] = _save_bytes(res["image"], "png")
            except Exception as exc:  # noqa: BLE001
                box["err"] = exc

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        while t.is_alive():
            t.join(timeout=0.5)
            yield "%s (%d/%d)" % (stages["label"], i + 1, n), (results or None)
        if "err" in box:
            logging.getLogger("studio").warning("generate_images failed: %s", box["err"])
            yield _friendly_error(box["err"]), (results or None)
            return
        results = results + [box["path"]]
        yield "✅ %d/%d 완료" % (i + 1, n), results
    yield "✅ 완료 (%d장)" % len(results), results


def edit_images(target_path, ref_path, ref_mode, edit_instr):
    """이미지 편집: 대상만→프롬프트 편집 / 레퍼런스+대상→분위기 이식·장면 합성. (상태, 이미지) yield."""
    if not target_path:
        yield "편집할 대상 사진을 올려 주세요.", None
        return
    if backend.sfw_violation(edit_instr):
        yield SFW_REFUSAL, None
        return
    stages = {"label": "✨ 편집 중..."}

    def _on_stage(s):
        stages["label"] = STAGE_LABELS.get(s, stages["label"])

    def _work():
        mode = "sfw"
        with open(target_path, "rb") as f:
            tgt = f.read()
        if ref_path:
            with open(ref_path, "rb") as f:
                ref = f.read()
            out = pipeline.edit_image_ref(tgt, ref, edit_instr or "", mode=mode,
                                          composite=("합성" in (ref_mode or "")))
        else:
            out = pipeline.edit_image(tgt, edit_instr or "enhance and refine, keep composition", mode=mode)
        return _save_bytes(out, "png")

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
        logging.getLogger("studio").warning("edit_images failed: %s", box["err"])
        yield _friendly_error(box["err"]), None
        return
    yield "✅ 완료", box["path"]


def generate_video(vmode, prompt, input_image, input_video, aspect, edit_instr, motion_only, expand_on):
    """비디오 생성. vmode: '텍스트→영상' | '이미지→영상' | '영상→영상'. (상태, 영상경로) yield."""
    is_i2v = "이미지" in (vmode or "")
    is_v2v = "영상→영상" in (vmode or "")
    if is_i2v and not input_image:
        yield "이미지→영상: 입력 이미지를 올려 주세요.", None
        return
    if is_v2v and not input_video:
        yield "영상→영상: 입력 영상을 올려 주세요.", None
        return
    if not is_i2v and not is_v2v and not (prompt and prompt.strip()):
        yield "프롬프트를 입력해 주세요.", None
        return
    if backend.sfw_violation(prompt) or backend.sfw_violation(edit_instr):
        yield SFW_REFUSAL, None
        return

    stages = {"label": "⏳ 시작하는 중..."}

    def _on_stage(s):
        stages["label"] = STAGE_LABELS.get(s, stages["label"])

    def _work():
        img_mode = "sfw"
        if is_v2v:
            with open(input_video, "rb") as f:
                vbytes = f.read()
            res = pipeline.make_video(idea=prompt, prompt=prompt, aspect=aspect, mode=img_mode,
                                      source_video=vbytes, edit_instructions=(edit_instr or None),
                                      expand=bool(expand_on), on_stage=_on_stage)
        elif is_i2v:
            with open(input_image, "rb") as f:
                ibytes = f.read()
            # 모션만이면 편집 생략, 아니면 edit_instr(없으면 prompt)로 편집 후 영상.
            ei = None if motion_only else (edit_instr or prompt or None)
            res = pipeline.make_video(idea=prompt, prompt=prompt, aspect=aspect, mode=img_mode,
                                      input_image=ibytes, edit_instructions=ei,
                                      expand=bool(expand_on), on_stage=_on_stage)
        else:
            res = pipeline.make_video(idea=prompt, prompt=None, aspect=aspect, mode=img_mode,
                                      edit_instructions=(edit_instr or None),
                                      expand=bool(expand_on), on_stage=_on_stage)
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


def concat_videos(video_files):
    """여러 영상을 ffmpeg로 이어붙여 긴 영상 1개로. (상태, 영상경로) 반환."""
    paths = []
    for f in (video_files or []):
        p = f if isinstance(f, str) else getattr(f, "name", None)
        if p:
            paths.append(p)
    if len(paths) < 2:
        return "이어붙이려면 영상 2개 이상을 올려 주세요.", None
    import subprocess
    import tempfile
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    outp = os.path.join(OUTPUT_DIR, "concat_%s.mp4" % _ts_file())
    listf = tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w")
    try:
        for p in paths:
            listf.write("file '%s'\n" % os.path.abspath(p))
        listf.close()
        try:
            subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listf.name,
                            "-c", "copy", outp], check=True, capture_output=True, timeout=300)
        except Exception:
            subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listf.name,
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", outp],
                           check=True, capture_output=True, timeout=600)
        return "✅ %d개 이어붙임 완료" % len(paths), outp
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("studio").warning("concat_videos failed: %s", exc)
        return _friendly_error(exc), None
    finally:
        try:
            os.remove(listf.name)
        except Exception:
            pass


CSS = """
:root, body, gradio-app { font-family: 'Pretendard', 'Inter', system-ui, sans-serif; }
body, gradio-app, .gradio-container { background-color: #121212 !important; color: #ececec !important; }
#result-img, #result-vid { border-radius: 12px; background:#1e1e1e !important; border:1px solid #333; }
#sidebar-img, #sidebar-vid { background:#181818 !important; padding:18px; border-radius:12px; border:1px solid #2c2c2c; }
/* 다크 보강: 인풋/탭/마크다운/갤러리 가독성 */
.gradio-container input, .gradio-container textarea, .gradio-container select { background:#1c1c1c !important; color:#ececec !important; border-color:#3a3a3a !important; }
.gradio-container .tab-nav button { color:#bbb !important; }
.gradio-container .tab-nav button.selected { color:#fff !important; border-bottom-color:#8b5cf6 !important; }
.gradio-container .prose, .gradio-container .prose * { color:#dcdcdc !important; }
.gradio-container a { color:#a78bfa !important; }
.gallery-item, .grid-wrap { background:#1a1a1a !important; }
"""

# 라이트/다크 양쪽 변수를 모두 다크 값으로 고정 → 로그인 페이지 등 .dark 클래스가
# 주입되지 않는 화면까지 일관되게 어둡게 렌더된다(JS 의 .dark 강제와 이중 안전장치).
THEME = gr.themes.Base(
    primary_hue="violet",
    secondary_hue="violet",
    neutral_hue="slate",
).set(
    body_background_fill="#121212", body_background_fill_dark="#121212",
    body_text_color="#ececec", body_text_color_dark="#ececec",
    body_text_color_subdued="#9a9a9a", body_text_color_subdued_dark="#9a9a9a",
    background_fill_primary="#1a1a1a", background_fill_primary_dark="#1a1a1a",
    background_fill_secondary="#181818", background_fill_secondary_dark="#181818",
    block_background_fill="#1e1e1e", block_background_fill_dark="#1e1e1e",
    block_border_color="#333", block_border_color_dark="#333",
    block_label_background_fill="#1a1a1a", block_label_background_fill_dark="#1a1a1a",
    block_label_text_color="#cfcfcf", block_label_text_color_dark="#cfcfcf",
    block_title_text_color="#ececec", block_title_text_color_dark="#ececec",
    border_color_primary="#333", border_color_primary_dark="#333",
    panel_background_fill="#181818", panel_background_fill_dark="#181818",
    input_background_fill="#1c1c1c", input_background_fill_dark="#1c1c1c",
    input_border_color="#3a3a3a", input_border_color_dark="#3a3a3a",
    input_placeholder_color="#777", input_placeholder_color_dark="#777",
    button_secondary_background_fill="#2a2a2a", button_secondary_background_fill_dark="#2a2a2a",
    button_secondary_text_color="#ececec", button_secondary_text_color_dark="#ececec",
)

JS_CODE = """
function() {
    document.body.classList.add("dark");
    document.querySelector("gradio-app").classList.add("dark");
    window.addEventListener("beforeunload", function () { navigator.sendBeacon('/shutdown'); });
}
"""


def build_ui():
    aspects = list(backend.ASPECTS.keys())
    with gr.Blocks() as demo:   # theme/css/js 는 Gradio 6 에서 mount_gradio_app()로 전달(아래)
        with gr.Row():
            with gr.Column(scale=8):
                gr.Markdown("# 🚀 Image & Video Studio")
                gr.Markdown("Made by Hyunho Kim · ")
            with gr.Column(scale=1, min_width=140):
                gr.Markdown("")

        with gr.Tabs():
            # ---- 이미지 생성 (텍스트→이미지, N장) ----
            with gr.Tab("🎨 이미지 생성"):
                with gr.Row():
                    with gr.Column(scale=2, elem_id="sidebar-img"):
                        g_prompt = gr.Textbox(label="프롬프트", lines=4,
                                              placeholder="만들고 싶은 이미지를 자유롭게 적어 주세요.")
                        g_count = gr.Radio(choices=[1, 2, 4, 6], value=1, label="장수")
                        g_aspect = gr.Dropdown(choices=aspects, value="1:1", label="비율")
                        with gr.Accordion("고급 설정", open=False):
                            g_expand = gr.Checkbox(label="프롬프트 자동 다듬기", value=True)
                        with gr.Row():
                            g_go = gr.Button("✨ 생성", variant="primary")
                            g_stop = gr.Button("⏹️ 중지", variant="stop")
                    with gr.Column(scale=3):
                        g_status = gr.Textbox(label="진행 상태", interactive=False)
                        g_gallery = gr.Gallery(label="결과", elem_id="result-img", height=520,
                                               columns=2, object_fit="contain")
                g_evt = g_go.click(fn=generate_images,
                                   inputs=[g_prompt, g_count, g_aspect, g_expand],
                                   outputs=[g_status, g_gallery], api_name=False)
                g_stop.click(fn=None, inputs=None, outputs=None, cancels=[g_evt], api_name=False)

            # ---- 이미지 편집 (레퍼런스 + 대상) ----
            with gr.Tab("🖌️ 이미지 편집"):
                gr.Markdown("**레퍼런스**(분위기·선택)와 **대상**(편집할 사진)을 올리세요. "
                            "대상만 넣으면 프롬프트대로 편집, 레퍼런스도 넣으면 그 분위기로 재구성/합성합니다.")
                with gr.Row():
                    with gr.Column(scale=2, elem_id="sidebar-img"):
                        with gr.Row():
                            e_ref = gr.Image(label="레퍼런스(분위기, 선택)", type="filepath", height=190)
                            e_target = gr.Image(label="대상(편집할 사진)", type="filepath", height=190)
                        e_mode = gr.Radio(choices=["분위기 이식", "장면 합성"], value="분위기 이식",
                                          label="레퍼런스 적용 방식(레퍼런스 있을 때)")
                        e_instr = gr.Textbox(label="편집 지시", lines=2,
                                             placeholder="예: 배경을 노을로 / 더 선명하게 (레퍼런스 있으면 추가 지시)")
                        with gr.Row():
                            e_go = gr.Button("🖌️ 편집", variant="primary")
                            e_stop = gr.Button("⏹️ 중지", variant="stop")
                    with gr.Column(scale=3):
                        e_status = gr.Textbox(label="진행 상태", interactive=False)
                        e_out = gr.Image(label="결과", elem_id="result-img", height=520,
                                         type="filepath", interactive=False)
                        e_dl = gr.DownloadButton("⬇️ 다운로드", variant="secondary")
                e_evt = e_go.click(fn=edit_images,
                                   inputs=[e_target, e_ref, e_mode, e_instr],
                                   outputs=[e_status, e_out], api_name=False)
                e_stop.click(fn=None, inputs=None, outputs=None, cancels=[e_evt], api_name=False)
                e_out.change(fn=lambda p: gr.update(value=p), inputs=[e_out],
                             outputs=[e_dl], api_name=False)

            # ---- 비디오 생성 (T2V / I2V / V2V) + 이어붙이기 ----
            with gr.Tab("🎬 비디오 생성"):
                with gr.Row():
                    with gr.Column(scale=2, elem_id="sidebar-vid"):
                        v_mode = gr.Radio(choices=["텍스트→영상", "이미지→영상", "영상→영상"],
                                          value="텍스트→영상", label="모드")
                        v_prompt = gr.Textbox(label="프롬프트 / 지시", lines=3,
                                              placeholder="영상으로 만들 장면·모션을 적어 주세요.")
                        v_image = gr.Image(label="입력 이미지(이미지→영상)", type="filepath", visible=False)
                        v_video = gr.Video(label="입력 영상(영상→영상)", visible=False)
                        v_motion = gr.Checkbox(label="모션만(편집 생략)", value=False, visible=False)
                        v_aspect = gr.Dropdown(choices=["9:16", "16:9", "1:1"], value="9:16", label="비율")
                        with gr.Accordion("고급 설정", open=False):
                            v_instr = gr.Textbox(label="편집 지시(이미지/영상 재구성 시)", lines=2)
                            v_expand = gr.Checkbox(label="프롬프트 자동 다듬기", value=True)
                        with gr.Row():
                            v_go = gr.Button("🎬 생성", variant="primary")
                            v_stop = gr.Button("⏹️ 중지", variant="stop")
                    with gr.Column(scale=3):
                        v_status = gr.Textbox(label="진행 상태", interactive=False)
                        v_out = gr.Video(label="결과", elem_id="result-vid", height=480)
                        with gr.Accordion("🔗 영상 이어붙이기(긴 영상 만들기)", open=False):
                            cat_in = gr.File(file_count="multiple", file_types=["video"],
                                             label="이어붙일 영상들(2개 이상)")
                            cat_go = gr.Button("🔗 이어붙이기")
                            cat_status = gr.Textbox(label="상태", interactive=False)
                            cat_out = gr.Video(label="긴 영상 결과", height=360)

                def _v_mode_change(m):
                    return (gr.update(visible=("이미지" in m)),
                            gr.update(visible=("영상→영상" in m)),
                            gr.update(visible=("이미지" in m)))
                v_mode.change(fn=_v_mode_change, inputs=[v_mode],
                              outputs=[v_image, v_video, v_motion], api_name=False)
                v_evt = v_go.click(
                    fn=generate_video,
                    inputs=[v_mode, v_prompt, v_image, v_video, v_aspect, v_instr, v_motion, v_expand],
                    outputs=[v_status, v_out], api_name=False,
                )
                v_stop.click(fn=None, inputs=None, outputs=None, cancels=[v_evt], api_name=False)
                cat_go.click(fn=concat_videos, inputs=[cat_in], outputs=[cat_status, cat_out], api_name=False)

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
    # Gradio 6.0: theme/css/js 는 Blocks 생성자가 아니라 mount_gradio_app()(또는 launch())로 전달해야
    # 적용된다(로그인 페이지 포함 앱 전역에 먹는다). Blocks 에 넘기면 무시 + DeprecationWarning.
    app_api = gr.mount_gradio_app(app_api, demo, path="/", root_path=root_path,
                                  auth=authenticate, auth_message=AUTH_MESSAGE,
                                  theme=THEME, css=CSS, js=JS_CODE)
    uvicorn.run(app_api, host="0.0.0.0", port=PORT)
