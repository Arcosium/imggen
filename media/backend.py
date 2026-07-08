"""미디어 생성 백엔드 설정의 단일 소스.

env 미설정 시 모든 값이 로컬 ComfyUI 기본값(127.0.0.1:8188)으로 떨어진다.
이 모듈은 Gradio/파이프라인을 import하지 않는다(순환 방지). 모델 체크포인트 이름은
여기(운영자 대상 설정)에 모이며, 사용자 UI엔 절대 노출되지 않는다.
"""
import os
import re

ASPECTS = {
    "1:1": (1024, 1024),
    "9:16": (576, 1024),
    "16:9": (1024, 576),
    "3:4": (768, 1024),
    "4:3": (1024, 768),
}


def _flag(name, default=False):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def aspect_dims(name):
    """비율 프리셋 이름 → (width, height). 미지 이름은 1:1로 안전 폴백."""
    return ASPECTS.get((name or "").strip(), (1024, 1024))


def nsfw_enabled(requested):
    """NSFW는 서버 env IMAGE_NSFW_ENABLED 가 켜진 경우에만 실효."""
    return bool(requested) and _flag("IMAGE_NSFW_ENABLED")


def resolve_image_mode(requested):
    """공개 mode 해석. uncensored는 서버 플래그가 켜진 경우만 허용, 아니면 sfw 강등."""
    if (requested or "sfw").strip().lower() == "uncensored" and _flag("IMAGE_NSFW_ENABLED"):
        return "uncensored"
    return "sfw"


# =============== [ SFW 방어선 ] ===============
# base txt2img(비검열 T5)·i2v(10Eros) 모델은 프롬프트 지시를 그대로 이행하므로,
# 공개 스튜디오를 "무조건 SFW" 로 만들려면 (1) 입력 차단어 게이트 + (2) 디퓨전 네거티브
# 두 겹으로 막는다. 완벽한 차단은 아니고(경량 백스톱), 명백한 성적/노출 요청을 걸러낸다.

# txt2img/i2v 에 항상 주입하는 SFW 네거티브(값이 없을 때의 기본값).
SFW_NEGATIVE = ("nsfw, nude, nudity, naked, topless, bottomless, explicit, sexual, "
                "porn, nipple, areola, genitalia, cleavage, lingerie, underwear, suggestive")

# 명백한 성인/노출 표현만 — 영어는 단어경계 매칭('analysis'의 anal, 'Sussex'의 sex 오탐 방지),
# 한국어는 부분일치. 오탐 큰 모호어(자지/보지/성기/사정/정액/삽입/변태 등)는 의도적으로 제외.
_NSFW_EN = (
    "nsfw", "nsfl", "nude", "nudes", "nudity", "naked", "topless", "bottomless",
    "explicit", "porn", "porno", "pornographic", "pornography", "hentai",
    "erotic", "erotica", "nipple", "nipples", "areola", "genital", "genitals",
    "genitalia", "penis", "vagina", "vulva", "pussy", "clitoris", "cock",
    "dick", "boob", "boobs", "tit", "tits", "titties", "cum", "cumshot",
    "creampie", "blowjob", "handjob", "fellatio", "cunnilingus", "masturbate",
    "masturbating", "masturbation", "orgasm", "ejaculation", "anal",
    "deepthroat", "bukkake", "fisting", "gangbang", "bdsm", "bondage",
    "fetish", "upskirt", "cameltoe", "underboob", "sideboob", "sex", "sexual",
    "sexy", "intercourse", "fuck", "fucking", "slut", "whore", "milf",
    "camgirl", "onlyfans", "xxx", "r18",
)
_NSFW_KO = (
    "누드", "나체", "알몸", "벌거벗", "벗은몸", "섹스", "성행위", "성관계",
    "성교", "음란", "포르노", "야동", "야설", "젖꼭지", "젖가슴", "자위",
    "페니스", "클리토리스", "노브라", "노팬티", "전라", "반라", "성인물",
    "19금", "야한", "페티시", "성적인", "섹시",
)
_NSFW_EN_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in _NSFW_EN) + r")\b", re.I)


def sfw_violation(text):
    """프롬프트에 명백한 성적/노출 표현이 있으면 매칭어(str), 없으면 None.
    공개 스튜디오 SFW 입력 게이트(경량 백스톱). base 모델이 비검열이라 UI 앞단에서 1차 차단한다."""
    t = (text or "").strip()
    if not t:
        return None
    m = _NSFW_EN_RE.search(t)
    if m:
        return m.group(1).lower()
    low = t.lower()
    for term in _NSFW_KO:
        if term in low:
            return term
    return None


def _pkg_workflow(name):
    return os.path.join(os.path.dirname(__file__), "workflows", name)


def _base_url():
    return (os.environ.get("COMFYUI_BASE_URL") or "http://127.0.0.1:8188").rstrip("/")


def image_config():
    return {
        "base_url": _base_url(),
        "txt2img_workflow": os.environ.get("COMFYUI_TXT2IMG_WORKFLOW") or _pkg_workflow("txt2img.json"),
        "edit_workflow": os.environ.get("COMFYUI_EDIT_WORKFLOW") or _pkg_workflow("edit.json"),
        "ckpt": os.environ.get("COMFYUI_CKPT") or "FHDR_ComfyUI-Q8_0.gguf",
        "edit_ckpt": os.environ.get("COMFYUI_EDIT_CKPT") or "qwen-image-edit-2511-Q4_K_M.gguf",
        "t5": os.environ.get("COMFYUI_T5") or "Kaoru8-t5xxl-unchained-Q4_0.gguf",
        "clip_l": os.environ.get("COMFYUI_CLIP_L") or "clip_l.safetensors",
        "vae": os.environ.get("COMFYUI_VAE") or "ae.safetensors",
        "nsfw_lora": os.environ.get("COMFYUI_NSFW_LORA") or "qwen-image-edit-plus-nsfw-lora.safetensors",
        "nsfw_lora_weight": float(os.environ.get("COMFYUI_NSFW_LORA_WEIGHT") or "0.9"),
        # 레퍼런스+대상 2-이미지 편집(Qwen-Image-Edit-Plus: image1=대상·image2=레퍼런스).
        "edit_ref_workflow": os.environ.get("COMFYUI_EDIT_REF_WORKFLOW") or _pkg_workflow("edit_ref.json"),
        "edit_ref_ckpt": os.environ.get("COMFYUI_EDIT_REF_CKPT") or "qwen-image-edit-2511-Q4_K_M.gguf",
    }


def video_config():
    # 영상 = LTX-2.3(10Eros, UnetLoaderGGUF) + gemma 텍스트 인코더 + LTX VAE.
    # 인코더/projection/VAE 파일명은 i2v.json 에 하드코딩(edit_ref.json 과 동일 패턴)되어
    # 여기 t5/vae 값은 워크플로에서 쓰이지 않는다(참고용). LTXVImgToVideo 의 length(=출력 프레임수,
    # %FRAMES%로 주입)는 (8n+1) 이어야 한다. 24fps 기준 길이: 49≈2s·73≈3s·97≈4s·121≈5s.
    # 길이↑=생성시간↑(프레임당 ~10-17s on GB10). 기본 97(≈4s). COMFYUI_VIDEO_FRAMES 로 조정.
    # LTX 는 cfg≈3, fps 24 가 자연스럽다.
    return {
        "base_url": _base_url(),
        "i2v_workflow": os.environ.get("COMFYUI_I2V_WORKFLOW") or _pkg_workflow("i2v.json"),
        "video_ckpt": os.environ.get("COMFYUI_VIDEO_MODEL") or "10Eros_v1-Q4_K_M.gguf",
        "t5": os.environ.get("COMFYUI_T5") or "gemma_3_12B_it_fp4_mixed.safetensors",
        "vae": os.environ.get("COMFYUI_VAE") or "ltx-2-3-22b-VAE.safetensors",
        "frames": int(os.environ.get("COMFYUI_VIDEO_FRAMES") or "97"),
        "fps": int(os.environ.get("COMFYUI_VIDEO_FPS") or "24"),
        "steps": int(os.environ.get("COMFYUI_VIDEO_STEPS") or "20"),
        "cfg": float(os.environ.get("COMFYUI_VIDEO_CFG") or "3.0"),
    }


def llm_config():
    """프롬프트 확장용 OpenAI-호환 LLM 설정. base_url 미설정이면 enabled=False(확장 폴백)."""
    base = (os.environ.get("IMAGE_PROMPT_LLM_BASE_URL")
            or os.environ.get("LOCAL_LLM_BASE_URL") or "").rstrip("/")
    return {
        "enabled": bool(base),
        "base_url": base,
        "api_key": os.environ.get("IMAGE_PROMPT_LLM_API_KEY") or os.environ.get("LOCAL_LLM_API_KEY") or "local",
        "model": os.environ.get("IMAGE_PROMPT_LLM_MODEL") or os.environ.get("LOCAL_LLM_MODEL") or "local-model",
        # 로컬 LLM이 추론(reasoning) 모델이라 넉넉한 max_tokens 로 호출하면 응답이
        # 오래 걸린다(수십 초~수분). 30s 면 timeout 으로 expand_prompt 가 원문 폴백한다.
        "timeout": int(os.environ.get("IMAGE_PROMPT_LLM_TIMEOUT") or "600"),
    }
