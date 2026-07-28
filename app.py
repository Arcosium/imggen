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
    "expand": "아이디어 다듬는 중...",
    "txt2img": "이미지 생성 중...",
    "edit": "고화질 편집 중...",
    "done": "완료",
}


def _friendly_error(exc):
    """내부 예외를 사용자용 일반 메시지로. 백엔드/소켓 세부정보 비노출."""
    return "생성에 실패했습니다. 미디어 백엔드 연결을 확인해 주세요."


# 공개 스튜디오는 전체이용가(SFW) 전용 — 성적/노출 요청은 생성 전에 차단한다.
SFW_REFUSAL = "부적절(성적·노출) 요청은 생성할 수 없습니다. 이 스튜디오는 전체이용가 콘텐츠만 제공합니다."


# =============== [ GPU 단일 점유 — 생성/편집 동시 실행 금지 ] ===============
# 생성(txt2img)과 편집(edit)은 서로 다른 체크포인트를 VRAM 에 올린다. 동시에 돌면 OOM 이
# 나서 두 작업이 다 죽는다. 그래서 락 하나로 **한 번에 하나만** 돌린다.
# 대기시키지 않고 즉시 거절한다(기다리게 하면 Gradio 진행표시가 멈춘 것처럼 보인다).
#
# 2026-07-28: 프로세스 전역(threading.Lock) → 프로세스 **간**(arcgpu flock) 으로 넓혔다.
# 다른 앱(ArcAI.ve 이미지 스튜디오)이 같은 백엔드·같은 VRAM 을 쓰는데 락을 공유하지 않아
# 서로 끼어들었다 — NVRM OOM 210건/7일. 같은 락 파일을 여는 프로세스는 모두 직렬화된다.
from arcgpu import GpuLock

_GPU_LOCK = GpuLock()
BUSY_MSG = "지금 다른 작업(생성 또는 편집)이 진행 중입니다. 끝난 뒤 다시 시도해 주세요."


def _release_gpu_after(worker):
    """워커 스레드가 끝난 뒤 락을 푼다.

    ⏹️ 중지(Gradio cancels)는 제너레이터에 GeneratorExit 를 던질 뿐, 백엔드에 보낸 작업은
    그대로 돈다. 그때 락을 바로 풀면 다음 작업이 겹쳐 붙어 결국 OOM 이다 — 워커가 실제로
    끝날 때까지 붙들고 있는다. (Lock 은 RLock 과 달리 다른 스레드에서 release 해도 된다.)"""
    if worker is None or not worker.is_alive():
        _GPU_LOCK.release()
        return

    def _wait():
        worker.join()
        _GPU_LOCK.release()

    threading.Thread(target=_wait, daemon=True).start()


# =============== [ 인증: 로그인 / 가입 ] ===============
# auth_message 는 로그인 페이지에 HTML 그대로 렌더된다(Gradio 기본 로그인 화면은 gr.Blocks 의
# theme/css 가 닿지 않으므로, 여기 <style> 을 끼워 로그인 화면까지 종이/잉크 원장 테마로 통일한다).
AUTH_MESSAGE = (
    '<style>'
    "@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;600;900&"
    "family=Noto+Sans+KR:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');"
    'body,gradio-app,.gradio-container,.main,.app{background:#F5F1E8 !important;color:#1C1914 !important;'
    "font-family:'Noto Sans KR',sans-serif !important;}"
    '.gradio-container input,gradio-app input{background:transparent !important;color:#1C1914 !important;'
    'border:0 !important;border-bottom:1px solid #4A443A !important;border-radius:0 !important;}'
    '.gradio-container input:focus,gradio-app input:focus{outline:0 !important;'
    'border-bottom-color:#A63A22 !important;box-shadow:0 1px 0 0 #A63A22 !important;}'
    'gradio-app button{background:#1C1914 !important;color:#F5F1E8 !important;border:0 !important;'
    'border-radius:0 !important;}'
    'gradio-app button:hover{background:#A63A22 !important;}'
    'gradio-app .form,gradio-app .block,gradio-app fieldset{background:#F5F1E8 !important;'
    'border-color:rgba(28,25,20,.18) !important;border-radius:0 !important;box-shadow:none !important;}'
    'gradio-app label,gradio-app span,gradio-app h1,gradio-app h2,gradio-app p{color:#1C1914 !important;}'
    '</style>'
    '승인된 계정만 입장할 수 있습니다. 계정이 없다면 '
    '<a href="signup" style="color:#A63A22">가입 신청</a> 후 관리자 승인을 기다려 주세요.')


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


_SIGNUP_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    'family=Noto+Serif+KR:wght@400;600;900&family=Noto+Sans+KR:wght@400;500;700&'
    'family=IBM+Plex+Mono:wght@400;500;600&display=swap">'
)

_SIGNUP_CSS = """
:root{
  --paper:#F5F1E8; --ink:#1C1914; --ink-soft:#4A443A; --ink-faint:#6E675A;
  --rule:rgba(28,25,20,.8); --hairline:rgba(28,25,20,.18);
  --red:#A63A22; --red-deep:#8C2F1A;
  --serif:'Noto Serif KR','Apple SD Gothic Neo',serif;
  --sans:'Noto Sans KR',sans-serif; --mono:'IBM Plex Mono',ui-monospace,monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
     display:flex;min-height:100vh;align-items:center;justify-content:center}
::selection{background:rgba(166,58,34,.22)}
.sheet{width:340px;padding:36px 4px}
h1{font-family:var(--serif);font-weight:900;font-size:1.5rem;margin:0 0 6px;
   letter-spacing:.02em}
p.lede{color:var(--ink-faint);font-size:.85rem;margin:0 0 26px}
hr.rule{border:0;border-top:1px solid var(--rule);margin:0 0 26px}
label{display:block;font-family:var(--mono);font-size:.68rem;letter-spacing:.16em;
      text-transform:uppercase;color:var(--ink-faint);margin:18px 0 6px;font-weight:600}
input{width:100%;padding:9px 2px;border:0;border-bottom:1px solid var(--ink-soft);
      background:transparent;color:var(--ink);font-family:inherit;font-size:.95rem;
      min-height:40px;border-radius:0}
input:focus{outline:0;border-bottom-color:var(--red);box-shadow:0 1px 0 0 var(--red)}
input:focus-visible{outline:2px solid var(--red);outline-offset:3px}
button{margin-top:26px;width:100%;padding:12px;border:1px solid var(--ink);border-radius:0;
       background:var(--ink);color:var(--paper);font-family:var(--mono);font-size:.8rem;
       letter-spacing:.14em;text-transform:uppercase;cursor:pointer;min-height:44px;
       transition:background .18s ease,border-color .18s ease}
button:hover{background:var(--red);border-color:var(--red)}
button:focus-visible{outline:2px solid var(--red);outline-offset:2px}
a{color:inherit;border-bottom:1px solid var(--hairline);text-decoration:none}
a:hover{color:var(--red);border-bottom-color:var(--red)}
.back{margin-top:22px;font-family:var(--mono);font-size:.72rem;letter-spacing:.1em;
      color:var(--ink-faint);display:block}
.result{text-align:center}
.result .msg{font-family:var(--serif);font-size:1.05rem;margin:0 0 22px}
.result .msg.ok{color:var(--ink)}
.result .msg.fail{color:var(--red-deep)}
.result .links{font-family:var(--mono);font-size:.75rem;letter-spacing:.08em;color:var(--ink-faint)}
"""


def _signup_page_html():
    return """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>가입 신청</title>%s<style>%s</style></head><body>
<form class="sheet" method="post" action="signup">
 <h1>가입 신청</h1>
 <p class="lede">관리자 승인 후 로그인할 수 있습니다.</p>
 <hr class="rule">
 <label>아이디</label><input name="username" autocomplete="username" required>
 <label>비밀번호</label><input name="password" type="password" autocomplete="new-password" required>
 <button type="submit">가입 신청</button>
 <a class="back" href="./">← 로그인으로</a>
</form></body></html>""" % (_SIGNUP_FONTS, _SIGNUP_CSS)


def _signup_result_html(ok, msg):
    cls = "ok" if ok else "fail"
    return ("""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<title>가입 신청</title>%s<style>%s</style></head><body>
<div class="sheet result">
 <p class="msg %s">%s</p>
 <hr class="rule">
 <p class="links"><a href="./">로그인으로</a> &middot; <a href="signup">다시 신청</a></p>
</div></body></html>""" % (_SIGNUP_FONTS, _SIGNUP_CSS, cls, _html.escape(msg)))


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
    stages = {"label": "시작하는 중..."}

    def _on_stage(s):
        stages["label"] = STAGE_LABELS.get(s, stages["label"])

    if not _GPU_LOCK.acquire(blocking=False):
        yield BUSY_MSG, None
        return
    inflight = {"t": None}
    try:
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
            inflight["t"] = t
            t.start()
            while t.is_alive():
                t.join(timeout=0.5)
                yield "%s (%d/%d)" % (stages["label"], i + 1, n), (results or None)
            if "err" in box:
                logging.getLogger("studio").warning("generate_images failed: %s", box["err"])
                yield _friendly_error(box["err"]), (results or None)
                return
            results = results + [box["path"]]
            yield "%d/%d 완료" % (i + 1, n), results
        yield "완료 (%d장)" % len(results), results
    finally:
        _release_gpu_after(inflight["t"])


def edit_images(target_path, ref_path, ref_mode, edit_instr):
    """이미지 편집: 대상만→프롬프트 편집 / 레퍼런스+대상→분위기 이식·장면 합성. (상태, 이미지) yield."""
    if not target_path:
        yield "편집할 대상 사진을 올려 주세요.", None
        return
    if backend.sfw_violation(edit_instr):
        yield SFW_REFUSAL, None
        return
    stages = {"label": "편집 중..."}

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

    if not _GPU_LOCK.acquire(blocking=False):
        yield BUSY_MSG, None
        return
    t = threading.Thread(target=_runner, daemon=True)
    try:
        t.start()
        yield stages["label"], None
        while t.is_alive():
            t.join(timeout=0.5)
            yield stages["label"], None
        if "err" in box:
            logging.getLogger("studio").warning("edit_images failed: %s", box["err"])
            yield _friendly_error(box["err"]), None
            return
        yield "완료", box["path"]
    finally:
        _release_gpu_after(t)


CSS = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;600;900&family=Noto+Sans+KR:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root{
  --paper:#F5F1E8; --paper-dim:#EDE8DB;
  --ink:#1C1914; --ink-soft:#4A443A; --ink-faint:#6E675A;
  --rule:rgba(28,25,20,.8); --hairline:rgba(28,25,20,.18); --hairline-soft:rgba(28,25,20,.1);
  --red:#A63A22; --red-deep:#8C2F1A; --red-soft:#F0E2E0; --ok:#3F6B45;
  --serif:'Noto Serif KR','Apple SD Gothic Neo',serif;
  --sans:'Noto Sans KR',sans-serif; --mono:'IBM Plex Mono',ui-monospace,monospace;
}

:root, body, gradio-app { font-family: var(--sans); }
body, gradio-app, .gradio-container { background-color: var(--paper) !important; color: var(--ink) !important; }
::selection { background: rgba(166,58,34,.22); }

/* 카드가 아니라 괘선(rule)으로 면을 나눈다 — radius/shadow 전면 제거 */
* { border-radius: 0 !important; }
.gradio-container .block, .gradio-container .form, .gradio-container fieldset,
.gradio-container .panel { box-shadow: none !important; }

#result-img { background: var(--paper-dim) !important; border: 1px solid var(--rule); }
#sidebar-img { background: var(--paper-dim) !important; padding: 18px; border: 1px solid var(--hairline); }

/* 마스트헤드: 카드 대신 이중괘선으로 면을 나눈다 */
#studio-masthead { border-bottom: 1px solid var(--rule); padding-bottom: 14px; margin-bottom: 10px; }
#studio-title h1 {
  font-family: var(--serif) !important; font-weight: 900 !important;
  letter-spacing: .03em; text-transform: uppercase; margin: 0 !important;
}
#studio-byline p {
  font-family: var(--mono) !important; font-size: .78rem !important;
  letter-spacing: .08em; color: var(--ink-faint) !important; margin: 4px 0 0 !important;
}

/* 인풋: 바닥선만, 채움 없음 */
.gradio-container input, .gradio-container textarea, .gradio-container select {
  background: transparent !important; color: var(--ink) !important;
  border: 0 !important; border-bottom: 1px solid var(--ink-soft) !important;
}
.gradio-container input:focus, .gradio-container textarea:focus, .gradio-container select:focus {
  outline: 0 !important; border-bottom-color: var(--red) !important;
  box-shadow: 0 1px 0 0 var(--red) !important;
}
.gradio-container label span { font-family: var(--mono) !important; letter-spacing: .08em; }

/* 탭: 활성 = 잉크 글자 + red 하단 보더(필배지 아님) */
.gradio-container .tab-nav button { color: var(--ink-faint) !important; font-family: var(--mono); }
.gradio-container .tab-nav button.selected {
  color: var(--ink) !important; border-bottom: 3px solid var(--red) !important;
}

.gradio-container .prose, .gradio-container .prose * { color: var(--ink-soft) !important; }
.gradio-container a { color: var(--red) !important; }

/* 갤러리: 종이-딤 배경, 카드 그림자 없음 */
.gallery-item, .grid-wrap { background: var(--paper-dim) !important; box-shadow: none !important; }
"""

# 다크 고정이었던 구조를 종이 라이트 고정으로 뒤집는다. 라이트/다크 양쪽 변수를 같은 종이
# 값으로 채워 → 로그인 페이지 등 .dark 클래스가 주입되지 않는 화면까지 일관되게 렌더된다.
THEME = gr.themes.Base(
    primary_hue="red",
    secondary_hue="red",
    neutral_hue="stone",
    radius_size=gr.themes.sizes.radius_none,
    font=[gr.themes.GoogleFont("Noto Sans KR"), "ui-sans-serif", "system-ui", "sans-serif"],
    font_mono=[gr.themes.GoogleFont("IBM Plex Mono"), "ui-monospace", "Consolas", "monospace"],
).set(
    body_background_fill="#F5F1E8", body_background_fill_dark="#F5F1E8",
    body_text_color="#1C1914", body_text_color_dark="#1C1914",
    body_text_color_subdued="#6E675A", body_text_color_subdued_dark="#6E675A",
    background_fill_primary="#F5F1E8", background_fill_primary_dark="#F5F1E8",
    background_fill_secondary="#EDE8DB", background_fill_secondary_dark="#EDE8DB",
    block_background_fill="#F5F1E8", block_background_fill_dark="#F5F1E8",
    block_border_color="rgba(28,25,20,.18)", block_border_color_dark="rgba(28,25,20,.18)",
    block_label_background_fill="#F5F1E8", block_label_background_fill_dark="#F5F1E8",
    block_label_text_color="#6E675A", block_label_text_color_dark="#6E675A",
    block_title_text_color="#1C1914", block_title_text_color_dark="#1C1914",
    border_color_primary="rgba(28,25,20,.18)", border_color_primary_dark="rgba(28,25,20,.18)",
    panel_background_fill="#EDE8DB", panel_background_fill_dark="#EDE8DB",
    input_background_fill="transparent", input_background_fill_dark="transparent",
    input_border_color="rgba(28,25,20,.18)", input_border_color_dark="rgba(28,25,20,.18)",
    input_placeholder_color="#6E675A", input_placeholder_color_dark="#6E675A",
    link_text_color="#A63A22", link_text_color_dark="#A63A22",
    link_text_color_hover="#8C2F1A", link_text_color_hover_dark="#8C2F1A",
    link_text_color_active="#8C2F1A", link_text_color_active_dark="#8C2F1A",
    link_text_color_visited="#A63A22", link_text_color_visited_dark="#A63A22",
    button_primary_background_fill="#1C1914", button_primary_background_fill_dark="#1C1914",
    button_primary_background_fill_hover="#A63A22", button_primary_background_fill_hover_dark="#A63A22",
    button_primary_text_color="#F5F1E8", button_primary_text_color_dark="#F5F1E8",
    button_primary_text_color_hover="#F5F1E8", button_primary_text_color_hover_dark="#F5F1E8",
    button_primary_border_color="#1C1914", button_primary_border_color_dark="#1C1914",
    button_primary_border_color_hover="#A63A22", button_primary_border_color_hover_dark="#A63A22",
    button_secondary_background_fill="transparent", button_secondary_background_fill_dark="transparent",
    button_secondary_background_fill_hover="#A63A22", button_secondary_background_fill_hover_dark="#A63A22",
    button_secondary_text_color="#A63A22", button_secondary_text_color_dark="#A63A22",
    button_secondary_text_color_hover="#F5F1E8", button_secondary_text_color_hover_dark="#F5F1E8",
    button_secondary_border_color="#A63A22", button_secondary_border_color_dark="#A63A22",
    button_secondary_border_color_hover="#A63A22", button_secondary_border_color_hover_dark="#A63A22",
    button_cancel_background_fill="transparent", button_cancel_background_fill_dark="transparent",
    button_cancel_background_fill_hover="#A63A22", button_cancel_background_fill_hover_dark="#A63A22",
    button_cancel_text_color="#A63A22", button_cancel_text_color_dark="#A63A22",
    button_cancel_text_color_hover="#F5F1E8", button_cancel_text_color_hover_dark="#F5F1E8",
    button_cancel_border_color="#A63A22", button_cancel_border_color_dark="#A63A22",
    button_cancel_border_color_hover="#A63A22", button_cancel_border_color_hover_dark="#A63A22",
)

JS_CODE = """
function() {
    window.addEventListener("beforeunload", function () { navigator.sendBeacon('/shutdown'); });
}
"""


def build_ui():
    aspects = list(backend.ASPECTS.keys())
    with gr.Blocks() as demo:   # theme/css/js 는 Gradio 6 에서 mount_gradio_app()로 전달(아래)
        with gr.Row(elem_id="studio-masthead"):
            with gr.Column(scale=8):
                gr.Markdown("# Image Studio", elem_id="studio-title")
                gr.Markdown("Made by Hyunho Kim · ", elem_id="studio-byline")
            with gr.Column(scale=1, min_width=140):
                gr.Markdown("")

        with gr.Tabs():
            # ---- 이미지 생성 (텍스트→이미지, N장) ----
            with gr.Tab("이미지 생성"):
                with gr.Row():
                    with gr.Column(scale=2, elem_id="sidebar-img"):
                        g_prompt = gr.Textbox(label="프롬프트", lines=4,
                                              placeholder="만들고 싶은 이미지를 자유롭게 적어 주세요.")
                        g_count = gr.Radio(choices=[1, 2, 4, 6], value=1, label="장수")
                        g_aspect = gr.Dropdown(choices=aspects, value="1:1", label="비율")
                        with gr.Accordion("고급 설정", open=False):
                            g_expand = gr.Checkbox(label="프롬프트 자동 다듬기", value=True)
                        with gr.Row():
                            g_go = gr.Button("생성", variant="primary")
                            g_stop = gr.Button("중지", variant="stop")
                    with gr.Column(scale=3):
                        g_status = gr.Textbox(label="진행 상태", interactive=False)
                        g_gallery = gr.Gallery(label="결과", elem_id="result-img", height=520,
                                               columns=2, object_fit="contain")
                g_evt = g_go.click(fn=generate_images,
                                   inputs=[g_prompt, g_count, g_aspect, g_expand],
                                   outputs=[g_status, g_gallery], api_name=False)
                g_stop.click(fn=None, inputs=None, outputs=None, cancels=[g_evt], api_name=False)

            # ---- 이미지 편집 (레퍼런스 + 대상) ----
            with gr.Tab("이미지 편집"):
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
                            e_go = gr.Button("편집", variant="primary")
                            e_stop = gr.Button("중지", variant="stop")
                    with gr.Column(scale=3):
                        e_status = gr.Textbox(label="진행 상태", interactive=False)
                        e_out = gr.Image(label="결과", elem_id="result-img", height=520,
                                         type="filepath", interactive=False)
                        e_dl = gr.DownloadButton("다운로드", variant="secondary")
                e_evt = e_go.click(fn=edit_images,
                                   inputs=[e_target, e_ref, e_mode, e_instr],
                                   outputs=[e_status, e_out], api_name=False)
                e_stop.click(fn=None, inputs=None, outputs=None, cancels=[e_evt], api_name=False)
                e_out.change(fn=lambda p: gr.update(value=p), inputs=[e_out],
                             outputs=[e_dl], api_name=False)

            # ---- 관리자 승인 ----
            with gr.Tab("관리자"):
                gr.Markdown("관리자만 사용할 수 있습니다. 가입 신청을 승인/거절합니다.")
                adm_status = gr.Textbox(label="상태", interactive=False)
                adm_pending = gr.Dropdown(choices=[], label="대기 중 신청", interactive=True)
                with gr.Row():
                    adm_refresh = gr.Button("새로고침")
                    adm_approve = gr.Button("승인", variant="primary")
                    adm_reject = gr.Button("거절", variant="stop")

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
            with gr.Tab("사용설명서"):
                gr.HTML(render_manual_html())
                gr.DownloadButton("원본(.docx) 다운로드", value=MANUAL_DOCX, variant="secondary")

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
    # cloudflared 가 localhost 로 프록시한다 — LAN 에 직접 열어둘 이유가 없다.
    uvicorn.run(app_api, host="127.0.0.1", port=PORT)
