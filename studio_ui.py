"""Image Studio presentation: shared by desktop browsers and the Android WebView."""
import gradio as gr
from hashlib import sha256

FONT_URL = ('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&'
            'family=Noto+Sans+KR:wght@400;500;600;700&display=swap')
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="%s">' % FONT_URL)
TOKENS = """
:root {
  --studio-bg: #111315; --studio-panel: #191c1f; --studio-raised: #23282c;
  --studio-text: #edf2ef; --studio-muted: #a9b3b7; --studio-line: #353c40;
  --studio-accent: #b6eca0; --studio-accent-hover: #c9f5b8; --studio-danger: #ffb4ab;
  --studio-font: 'Manrope', 'Noto Sans KR', system-ui, sans-serif;
  --studio-ease: cubic-bezier(.22, 1, .36, 1);
  color-scheme: dark;
}
"""
BRAND = """<div class="studio-brand"><span class="studio-symbol" aria-hidden="true">
<svg width="28" height="28" viewBox="0 0 28 28" fill="none"><path d="M3 10V3h7M18 3h7v7M25 18v7h-7M10 25H3v-7" stroke="currentColor" stroke-width="2"/><path d="m7 20 6-8 4 5 3-3 3 6H7Z" fill="currentColor"/><circle cx="19" cy="9" r="2" fill="currentColor"/></svg>
</span><div><h1>Image Studio</h1><p>Made by Hyunho Kim</p></div></div>"""
INTRO = """<div class="studio-intro"><div><h2>상상을 꺼내는 작업실.</h2>
<p>아이디어를 이미지로 만들고, 사진에 새로운 분위기를 더하세요.</p></div>
<div class="studio-intro-art" aria-hidden="true"><span></span><span></span><span></span></div></div>"""


def panel_heading(title, description):
    return '<div class="panel-heading"><h3>%s</h3><p>%s</p></div>' % (title, description)


def empty_canvas(edit=False):
    title = '새로운 장면을 기다리는 캔버스' if edit else '첫 이미지가 시작될 곳'
    text = '사진을 올리고 편집 지시를 적어 주세요.' if edit else '왼쪽에 아이디어를 적어 보세요. 완성된 이미지는 여기에 모입니다.'
    return '''<div class="studio-empty"><div class="canvas-art" aria-hidden="true">
    <span class="art-frame art-back"></span><span class="art-frame art-middle"></span>
    <span class="art-frame art-front"><span class="art-sun"></span><span class="art-landscape"></span></span>
    </div><h3>%s</h3><p>%s</p></div>''' % (title, text)


CSS = "@import url('%s');\n" % FONT_URL + TOKENS + """
body, gradio-app, .gradio-container { background: var(--studio-bg) !important; color: var(--studio-text) !important; font-family: var(--studio-font) !important; }
body { margin: 0; }
.gradio-container > .main { padding: 0 !important; }
::selection { background: #b6eca033; }
.gradio-container { overflow: visible !important; width: 100% !important; max-width: 1400px !important; padding: 24px clamp(16px, 2.8vw, 40px) 32px !important; }
.gradio-container * { box-sizing: border-box; }
.gradio-container .hide-container { background: transparent !important; border: 0 !important; }
.gradio-container .html-container { padding: 0 !important; }
.gradio-container .block, .gradio-container .form { box-shadow: none !important; }
.gradio-container .prose { color: var(--studio-muted); }
.gradio-container p, .gradio-container h1, .gradio-container h2, .gradio-container h3 { word-break: keep-all; }
.gradio-container a { color: var(--studio-accent); }
.gradio-container button, .gradio-container a, .gradio-container input, .gradio-container textarea, .gradio-container label {
  -webkit-tap-highlight-color: transparent;
}
.gradio-container button { transition: background .2s ease, border-color .2s ease, color .2s ease, transform .2s var(--studio-ease); }
.gradio-container button:active { transform: translateY(1px); }
.gradio-container button:focus-visible, .gradio-container a:focus-visible, .gradio-container summary:focus-visible {
  outline: 2px solid var(--studio-accent) !important; outline-offset: 4px;
}
.gradio-container input, .gradio-container textarea { font-family: var(--studio-font) !important; font-size: 14px !important; }
.gradio-container input:focus-visible, .gradio-container textarea:focus-visible { outline: 2px solid var(--studio-accent) !important; outline-offset: -2px; }
.gradio-container label span { letter-spacing: 0; }
.gradio-container .info { color: var(--studio-muted) !important; font-size: 12px !important; line-height: 1.75 !important; }
#studio-masthead { align-items: center; padding-bottom: 18px; border-bottom: 1px solid var(--studio-line); gap: 16px; }
#studio-masthead .block { overflow: visible !important; }
#studio-title { padding: 0 !important; }
.studio-brand { display: flex; align-items: center; gap: 13px; }
.studio-brand .studio-symbol { color: var(--studio-accent); background: #b6eca00e; border: 1px solid #b6eca035; width: 48px; height: 48px; border-radius: 14px; display: grid; place-items: center; }
.studio-brand h1 { margin: 0 !important; font-family: var(--studio-font) !important; font-size: 23px !important; font-weight: 800 !important; letter-spacing: -.9px; line-height: 1.35 !important; }
.studio-brand p { margin: 3px 0 0 !important; font-size: 12px !important; color: var(--studio-muted); }
#studio-account { text-align: right; font-size: 12px; color: var(--studio-muted); }
.account-links { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 12px; align-items: center; }
.account-links b { color: var(--studio-text); font-weight: 600; overflow-wrap: anywhere; }
.account-links a { border: 1px solid var(--studio-line); padding: 8px 12px; border-radius: 8px; text-decoration: none; transition: border-color .2s ease, color .2s ease; }
.account-links a:hover { border-color: var(--studio-accent); }
#studio-intro { padding: 0 !important; overflow: visible !important; }
.studio-intro { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 22px 0 18px; }
.studio-intro h2 { color: var(--studio-text); font-size: clamp(24px, 3vw, 36px); font-weight: 700; letter-spacing: -1.6px; line-height: 1.4; margin: 0 0 9px !important; }
.studio-intro p { margin: 0 !important; font-size: 14px; color: var(--studio-muted); line-height: 1.8; }
.studio-intro-art { width: 132px; height: 72px; position: relative; flex-shrink: 0; }
.studio-intro-art span { position: absolute; width: 52px; height: 60px; top: 6px; border: 1px solid #5b6960; border-radius: 9px; background: #1c2320; transition: transform .55s var(--studio-ease); }
.studio-intro-art span:nth-child(1) { left: 10px; transform: rotate(-16deg); }
.studio-intro-art span:nth-child(2) { left: 38px; transform: rotate(-1deg); background: #31402d; }
.studio-intro-art span:nth-child(3) { left: 67px; transform: rotate(16deg); background: var(--studio-accent); border-color: var(--studio-accent); }
.studio-intro-art:hover span:nth-child(1) { transform: translateX(-6px) rotate(-24deg); }
.studio-intro-art:hover span:nth-child(3) { transform: translateX(6px) rotate(24deg); }
#studio-tabs { border: 0 !important; }
#studio-tabs .tab-container.visually-hidden { visibility: hidden !important; }
#studio-tabs [role=tablist] { min-height: 48px; border-bottom: 0 !important; align-items: center; overflow: visible !important; gap: 6px; }
#studio-tabs > div:first-child { gap: 6px; border-bottom: 1px solid var(--studio-line); padding: 0 0 14px; margin-bottom: 18px; }
#studio-tabs [role=tablist] button { min-height: 42px; padding: 10px 22px; border: 1px solid transparent; border-radius: 9px !important; color: var(--studio-muted); font-size: 14px; font-weight: 600; }
#studio-tabs [role=tablist] button:hover { color: var(--studio-text); background: var(--studio-raised); }
#studio-tabs [role=tablist] button.selected { color: var(--studio-accent); border: 1px solid #b6eca029; background: #b6eca00e; }
#studio-tabs > .tabitem { padding: 0 !important; border: 0 !important; }
.workspace-row { gap: 24px !important; align-items: flex-start !important; }
.studio-tools { background: var(--studio-panel); border: 1px solid var(--studio-line); border-radius: 16px; padding: 24px !important; gap: 16px !important; }
.studio-tools > .block { border-radius: 10px; }
.panel-heading { padding-bottom: 16px; border-bottom: 1px solid var(--studio-line); }
.panel-heading h3 { font-size: 16px; font-weight: 700; color: var(--studio-text); margin: 0 0 7px !important; letter-spacing: -.4px; }
.panel-heading p { font-size: 12px; line-height: 1.8; color: var(--studio-muted); margin: 0 !important; }
.studio-heading { padding: 0 !important; overflow: visible !important; }
.studio-tools .block:not(.hide-container), .studio-status { overflow: visible !important; background: transparent !important; border: 0 !important; padding: 0 !important; }
.studio-tools .form { border: 0 !important; background: transparent !important; }
.studio-tools label:not(:has(input[type=radio])):not(:has(input[type=checkbox])) { padding: 0 0 8px !important; }
.studio-tools textarea, .studio-tools input:not([type=checkbox]):not([type=radio]) {
  color: var(--studio-text) !important; background: var(--studio-bg) !important; border: 1px solid var(--studio-line) !important; border-radius: 10px !important; padding: 13px !important; line-height: 1.75 !important;
}
.studio-tools textarea::placeholder, .studio-tools input::placeholder { color: var(--studio-muted) !important; }
.studio-tools .wrap:has(> input) { border-radius: 10px !important; background: var(--studio-bg) !important; }
.studio-tools input[type=radio], .studio-tools input[type=checkbox] { accent-color: var(--studio-accent); }
.studio-tools label:has(input[type=radio]) { flex: 1; justify-content: center; min-height: 43px; background: var(--studio-bg) !important; border-color: var(--studio-line) !important; border-radius: 9px !important; transition: background .2s ease, border-color .2s ease; }
.studio-tools label:has(input[type=radio]:checked) { border-color: #b6eca07a !important; background: #b6eca00c !important; }
.studio-tools label:has(input[type=radio]) input { margin-right: 8px; }
.studio-tools input[type=radio]:checked, .studio-tools input[type=checkbox]:checked { background-color: var(--studio-accent) !important; border-color: var(--studio-accent) !important; }
.studio-tools .accordion { background: transparent !important; border: 1px solid var(--studio-line) !important; border-radius: 10px !important; }
.studio-tools .accordion > button { min-height: 44px; padding: 13px !important; }
.studio-tools .accordion > div { padding: 0 13px 13px; }
.studio-actions { gap: 10px !important; padding-top: 2px; }
.studio-actions button { min-height: 48px; border-radius: 10px !important; font-size: 14px !important; font-weight: 700; }
.studio-primary { flex-grow: 3 !important; background: var(--studio-accent) !important; color: var(--studio-bg) !important; border-color: var(--studio-accent) !important; }
.studio-primary:hover { background: var(--studio-accent-hover) !important; transform: translateY(-1px); }
.studio-stop { flex-grow: 1 !important; color: var(--studio-muted) !important; background: transparent !important; border-color: var(--studio-line) !important; }
.studio-stop:hover { color: var(--studio-danger) !important; border-color: var(--studio-danger) !important; }
.studio-output { gap: 16px !important; min-width: 0 !important; }
.studio-output .panel-heading { border: 0; padding: 0; display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
.studio-output .panel-heading p { text-align: right; }
.studio-status { overflow: visible !important; background: var(--studio-panel) !important; border: 1px solid var(--studio-line) !important; border-radius: 10px !important; padding: 12px 16px !important; }
.form:has(> .studio-status) { border: 0 !important; background: transparent !important; }
.studio-status label { color: var(--studio-muted); font-size: 11px; }
.studio-status .input-container { border: 0 !important; }
.studio-status textarea { background: transparent !important; border: 0 !important; padding: 0 !important; box-shadow: none !important; color: var(--studio-text) !important; font-size: 13px !important; }
.studio-canvas { position: relative; gap: 0 !important; }
.studio-result { border: 1px solid var(--studio-line) !important; background-color: var(--studio-panel) !important; border-radius: 16px !important; min-height: 480px; }
.studio-result:has(.empty) { background-image: radial-gradient(#3c4540 1px, transparent 1px); background-size: 24px 24px; }
.studio-result .empty .icon { opacity: 0; }
.studio-result .grid-wrap { height: 100% !important; }
.studio-result .grid-wrap, .studio-result .gallery-item { background: var(--studio-bg) !important; border-radius: 9px; }
.studio-result img { object-fit: contain; }
.studio-tools .icon-button, .studio-tools .download-link,
.studio-result .icon-button, .studio-result .download-link { width: 36px !important; min-width: 36px !important; height: 36px !important; padding: 6px !important; }
.studio-tools .icon-button > div, .studio-result .icon-button > div { width: 20px !important; height: 20px !important; }
.studio-tools .download-link, .studio-result .download-link { padding: 0 !important; }
.studio-tools .icon-button svg, .studio-tools .download-link svg,
.studio-result .icon-button svg, .studio-result .download-link svg { width: 20px; height: 20px; flex-shrink: 0; }
.studio-placeholder { position: absolute !important; inset: 0; border: 0 !important; background: transparent !important; pointer-events: none; padding: 24px !important; display: flex !important; align-items: center; justify-content: center; }
.studio-canvas:has(.studio-result img[src]) .studio-placeholder { display: none !important; }
.studio-empty { width: 100%; max-width: 330px; text-align: center; }
.studio-empty h3 { font-size: 17px; letter-spacing: -.5px; font-weight: 600; margin: 32px 0 10px !important; color: var(--studio-text); }
.studio-empty p { font-size: 13px; line-height: 1.9; color: var(--studio-muted); margin: 0 auto !important; max-width: 280px; }
.canvas-art { position: relative; width: 220px; height: 170px; margin: 0 auto; }
.art-frame { position: absolute; width: 116px; height: 140px; left: 52px; top: 15px; border-radius: 14px; border: 1px solid #58665c; transition: transform .6s var(--studio-ease); }
.art-back { transform: translate(-33px, 2px) rotate(-16deg); background: #1b2420; }
.art-middle { transform: translate(33px, -4px) rotate(15deg); background: #34492e; border-color: #67845b; }
.art-front { background: #c0deb0; border-color: #c0deb0; overflow: hidden; transform: rotate(-3deg); }
.art-sun { position: absolute; width: 25px; height: 25px; background: #f2f6e9; top: 22px; right: 18px; border-radius: 50%; }
.art-landscape { position: absolute; inset: 54px 0 0; background: #6b9259; clip-path: polygon(0 74%, 34% 13%, 63% 56%, 83% 28%, 100% 61%, 100% 100%, 0 100%); }
.studio-canvas:hover .art-back { transform: translate(-41px, 1px) rotate(-21deg); }
.studio-canvas:hover .art-middle { transform: translate(41px, -5px) rotate(21deg); }
.icon-button-wrapper button::after, .icon-button-wrapper a.download-link::after { right: 0 !important; }
.studio-download { min-height: 44px; border-radius: 10px !important; }
.studio-note { padding: 0 !important; overflow: visible !important; }
.studio-note p { margin: 0; font-size: 12px; line-height: 1.8; color: var(--studio-muted); }
#edit-help { margin-bottom: 16px; background: #1c2420; border: 1px solid #334636; border-radius: 12px; padding: 16px 20px !important; }
#edit-help p { font-size: 13px; line-height: 1.9; margin: 0; color: var(--studio-muted); }
#edit-help strong { color: var(--studio-text); }
#edit-inputs { gap: 12px !important; }
#edit-inputs button.center > .wrap { min-height: 0 !important; padding: 12px !important; font-size: 12px !important; line-height: 1.6; }
#edit-inputs > .block { background: var(--studio-bg) !important; border: 1px dashed #526057 !important; border-radius: 10px !important; }
#studio-manual { border: 1px solid var(--studio-line); border-radius: 16px; background: var(--studio-panel); padding: 24px; }
#studio-manual p, #studio-manual li { font-size: 14px; line-height: 1.9; }
#studio-admin { max-width: 720px; background: var(--studio-panel); border: 1px solid var(--studio-line); border-radius: 16px; padding: 24px; }
#studio-footer { padding: 20px 0 0 !important; border-top: 1px solid var(--studio-line); margin-top: 24px; }
#studio-footer p { font-size: 12px; color: var(--studio-muted); margin: 0; text-align: center; }
@media (prefers-reduced-motion: no-preference) {
  #studio-masthead { animation: studio-enter .5s var(--studio-ease) both; }
  .studio-intro { animation: studio-enter .6s .05s var(--studio-ease) both; }
  .tabitem[style*="display: flex"] .studio-tools { animation: studio-enter .45s var(--studio-ease) both; }
  .tabitem[style*="display: flex"] .studio-output { animation: studio-enter .55s .06s var(--studio-ease) both; }
  .studio-result img { animation: result-enter .4s var(--studio-ease) both; }
  .canvas-art { animation: studio-float 5s ease-in-out 2; }
  .studio-output[data-working="true"] .studio-status { border-color: #7b9d6c; }
  .studio-output[data-working="true"] .studio-status label::after { content: ''; display: inline-block; width: 6px; height: 6px; background: var(--studio-accent); border-radius: 50%; margin-left: 8px; animation: studio-pulse 1.5s ease-in-out infinite; }
}
@keyframes studio-enter { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
@keyframes result-enter { from { opacity: 0; transform: scale(.97); } to { opacity: 1; transform: scale(1); } }
@keyframes studio-float { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-7px); } }
@keyframes studio-pulse { 0%,100% { opacity: 1; } 50% { opacity: .35; } }
@media (max-width: 960px) {
  .gradio-container { padding: 24px !important; }
  .workspace-row { flex-direction: column !important; }
  .workspace-row > .column { width: 100%; flex: auto !important; }
  .studio-tools { min-width: 0 !important; }
  .studio-result { height: 460px !important; min-height: 460px; }
}
@media (max-width: 520px) {
  .gradio-container { padding: 18px 16px 28px !important; }
  #studio-masthead { flex-wrap: nowrap !important; gap: 10px; padding-bottom: 18px; }
  #studio-masthead > .column { min-width: 0 !important; }
  #studio-masthead > .column:first-child { flex: 1 1 auto !important; }
  #studio-masthead > .column:last-child { flex: 0 1 auto !important; max-width: 122px; }
  .studio-brand { gap: 9px; }
  .studio-brand .studio-symbol { width: 37px; height: 37px; border-radius: 11px; flex-shrink: 0; }
  .studio-brand .studio-symbol svg { width: 23px; height: 23px; }
  .studio-brand h1 { font-size: 19px !important; letter-spacing: -.7px; white-space: nowrap; }
  .studio-brand p { font-size: 12px !important; }
  .account-links { gap: 5px; font-size: 11px; }
  .account-links a { padding: 6px 8px; }
  .studio-intro { padding: 28px 0 24px; gap: 12px; }
  .studio-intro h2 { font-size: 25px; letter-spacing: -1px; }
  .studio-intro p { font-size: 12px; max-width: 250px; }
  .studio-intro-art { display: none; }
  #studio-tabs .tab-container.visually-hidden { visibility: hidden !important; }
#studio-tabs [role=tablist] { min-height: 48px; border-bottom: 0 !important; align-items: center; overflow: visible !important; gap: 6px; }
#studio-tabs > div:first-child { gap: 4px; margin-bottom: 20px; padding-bottom: 12px; }
  #studio-tabs [role=tablist] button { padding: 10px 15px; font-size: 13px; }
  .workspace-row { gap: 24px !important; }
  .studio-tools { padding: 20px !important; gap: 18px !important; border-radius: 14px; }
  .studio-result { height: 390px !important; min-height: 390px; }
  .studio-output .panel-heading p { font-size: 11px; }
  .studio-output .panel-heading h3 { font-size: 15px; }
  #edit-help { padding: 14px 16px !important; }
  #edit-inputs > .block { flex: 1 1 120px !important; min-width: 0 !important; height: 190px !important; }
  #edit-inputs [data-testid=block-info] { font-size: 11px; }
  #studio-manual, #studio-admin { padding: 20px; }
}
@media (max-width: 360px) {
  #studio-masthead { flex-wrap: wrap !important; }
  #studio-masthead > .column:first-child, #studio-masthead > .column:last-child { width: 100%; max-width: none; flex: auto !important; }
  .account-links { justify-content: flex-start; gap: 10px; }
  .studio-output .panel-heading { flex-wrap: wrap; gap: 4px; }
}
@media (prefers-reduced-motion: reduce) {
  .gradio-container *, .gradio-container *::before, .gradio-container *::after { animation: none !important; transition: none !important; scroll-behavior: auto !important; }
}
"""

THEME = gr.themes.Base(
    primary_hue='green', secondary_hue='green', neutral_hue='gray',
    font=[gr.themes.GoogleFont('Manrope'), gr.themes.GoogleFont('Noto Sans KR'), 'system-ui', 'sans-serif'],
).set(**{
    key + suffix: value
    for key, value in {
        'body_background_fill': '#111315', 'body_text_color': '#edf2ef',
        'body_text_color_subdued': '#a9b3b7', 'background_fill_primary': '#191c1f',
        'background_fill_secondary': '#23282c', 'block_background_fill': '#191c1f',
        'block_border_color': '#353c40', 'block_label_background_fill': '#191c1f',
        'block_label_text_color': '#a9b3b7', 'block_title_text_color': '#edf2ef',
        'border_color_primary': '#353c40', 'panel_background_fill': '#191c1f',
        'input_background_fill': '#111315', 'input_border_color': '#353c40',
        'input_placeholder_color': '#a9b3b7', 'link_text_color': '#b6eca0',
        'link_text_color_hover': '#c9f5b8', 'link_text_color_active': '#c9f5b8',
        'link_text_color_visited': '#b6eca0', 'button_primary_background_fill': '#b6eca0',
        'button_primary_background_fill_hover': '#c9f5b8', 'button_primary_text_color': '#111315',
        'button_primary_text_color_hover': '#111315', 'button_primary_border_color': '#b6eca0',
        'button_primary_border_color_hover': '#c9f5b8', 'button_secondary_background_fill': '#23282c',
        'button_secondary_background_fill_hover': '#30383d', 'button_secondary_text_color': '#edf2ef',
        'button_secondary_text_color_hover': '#edf2ef', 'button_secondary_border_color': '#353c40',
        'button_secondary_border_color_hover': '#65776b', 'button_cancel_background_fill': '#191c1f',
        'button_cancel_background_fill_hover': '#332421', 'button_cancel_text_color': '#ffb4ab',
        'button_cancel_text_color_hover': '#ffb4ab', 'button_cancel_border_color': '#353c40',
        'button_cancel_border_color_hover': '#ffb4ab',
    }.items() for suffix in ('', '_dark')
})

# Observe only the displayed status; server jobs and their events stay unchanged.
UI_JS = """(() => {
  if (window.__studioStatusTimer) clearInterval(window.__studioStatusTimer);
  const syncStatus = () => {
    for (const id of ['gen-output', 'edit-output']) {
      const panel = document.getElementById(id);
      if (!panel) continue;
      const status = panel.querySelector('.studio-status');
      if (status && !status.hasAttribute('aria-live')) status.setAttribute('aria-live', 'polite');
      const field = panel.querySelector('.studio-status textarea, .studio-status input');
      const value = field ? field.value : '';
      const working = /경과|중\\.\\.\\./.test(value) && !/완료|중지|실패/.test(value);
      const state = String(working);
      if (panel.dataset.working !== state) panel.dataset.working = state;
    }
  };
  syncStatus();
  window.__studioStatusTimer = setInterval(syncStatus, 1000);
  /* local-only */
})();"""

AUTH_CSS = TOKENS + """
body,gradio-app,.gradio-container,.main,.app { background:#111315 !important; color:#edf2ef !important; font-family:var(--studio-font) !important; }
gradio-app input { background:#111315 !important; color:#edf2ef !important; border:1px solid #353c40 !important; border-radius:10px !important; padding:13px !important; }
gradio-app input:focus-visible { outline:2px solid #b6eca0 !important; outline-offset:2px; }
gradio-app button { background:#b6eca0 !important; color:#111315 !important; border:1px solid #b6eca0 !important; border-radius:10px !important; min-height:46px; transition:background .2s ease; }
gradio-app button:hover { background:#c9f5b8 !important; }
gradio-app button:focus-visible,gradio-app a:focus-visible { outline:2px solid #b6eca0; outline-offset:4px; }
gradio-app .block { padding:16px !important; }
gradio-app .form,gradio-app .block,gradio-app fieldset { background:#191c1f !important; border-color:#353c40 !important; border-radius:14px !important; box-shadow:none !important; }
gradio-app label,gradio-app span,gradio-app h1,gradio-app h2,gradio-app p { color:#edf2ef !important; }
.auth-welcome { text-align:left; padding:6px 12px 20px; }
.auth-welcome .studio-brand { display:flex; align-items:center; gap:12px; }
.auth-welcome .studio-symbol { color:#b6eca0 !important; width:42px; height:42px; display:grid; place-items:center; flex-shrink:0; }
.auth-welcome .studio-brand h1 { font-size:21px; font-weight:700; margin:0; letter-spacing:-.6px; }
.auth-welcome .studio-brand p { font-size:12px; margin:4px 0 0; }
.auth-welcome h2 { font-size:23px; margin:20px 0 10px; letter-spacing:-.7px; }
.auth-welcome p { word-break:keep-all; font-size:13px; color:#a9b3b7 !important; line-height:1.8; }
.auth-welcome a { color:#b6eca0 !important; }
"""
# Gradio's login page requests theme.css?v=undefined, which can stay cached.
# Load the current theme again with a content version after that default link.
AUTH_THEME_VERSION = sha256(THEME._get_theme_css().encode()).hexdigest()[:16]
AUTH_MESSAGE = (FONTS + '<link rel="stylesheet" href="theme.css?v=studio-%s">' % AUTH_THEME_VERSION
                + '<style>' + AUTH_CSS + '</style><div class="auth-welcome">'
                + BRAND + '<h2>다시, 작업실로.</h2><p>승인된 계정만 입장할 수 있습니다. 계정이 없다면 '
                '<a href="signup">가입 신청</a> 후 관리자 승인을 기다려 주세요.</p></div>')
SIGNUP_CSS = TOKENS + """
* { box-sizing:border-box; }
body { margin:0; padding:24px; background:var(--studio-bg); color:var(--studio-text); font-family:var(--studio-font); display:flex; min-height:100dvh; align-items:center; justify-content:center; }
.sheet { width:100%; max-width:420px; background:var(--studio-panel); border:1px solid var(--studio-line); border-radius:20px; padding:36px; }
.brand { font-size:13px; color:var(--studio-accent); font-weight:700; margin-bottom:28px; }
h1 { font-weight:700; font-size:28px; letter-spacing:-1px; margin:0 0 10px; }
p.lede { color:var(--studio-muted); font-size:13px; line-height:1.8; margin:0 0 26px; word-break:keep-all; }
hr.rule { border:0; border-top:1px solid var(--studio-line); margin:0 0 26px; }
label { display:block; font-size:13px; color:var(--studio-muted); margin:20px 0 8px; font-weight:500; }
input { width:100%; padding:13px; border:1px solid var(--studio-line); background:var(--studio-bg); color:var(--studio-text); font:inherit; font-size:15px; min-height:48px; border-radius:10px; }
input:focus-visible,button:focus-visible,a:focus-visible { outline:2px solid var(--studio-accent); outline-offset:4px; }
button { margin-top:28px; width:100%; padding:13px; border:0; border-radius:10px; background:var(--studio-accent); color:var(--studio-bg); font:inherit; font-size:14px; font-weight:700; cursor:pointer; min-height:48px; transition:background .2s ease,transform .2s ease; }
button:hover { background:var(--studio-accent-hover); }
button:active { transform:translateY(1px); }
a { color:var(--studio-accent); text-decoration:none; }
a:hover { text-decoration:underline; }
.back { margin-top:24px; font-size:13px; display:inline-block; }
.result .msg { font-size:18px; margin:0 0 24px; line-height:1.8; word-break:keep-all; }
.result .msg.fail { color:var(--studio-danger); }
.result .links { font-size:13px; line-height:1.9; }
@media(max-width:520px) { body{padding:16px} .sheet{padding:28px 24px} }
@media(prefers-reduced-motion:reduce) { *{transition:none !important} }
"""
