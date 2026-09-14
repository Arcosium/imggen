"""미디어 생성 백엔드 설정의 단일 소스.

env 미설정 시 모든 값이 로컬 ComfyUI 기본값(127.0.0.1:8188)으로 떨어진다.
이 모듈은 Gradio/파이프라인을 import하지 않는다(순환 방지). 모델 체크포인트 이름은
여기(운영자 대상 설정)에 모이며, 사용자 UI엔 절대 노출되지 않는다.
"""
import os
import re

ASPECTS = {
    "1:1": (1024, 1024),
    "9:16": (720, 1280),
    "16:9": (1280, 720),
    "3:4": (960, 1280),
    "4:3": (1280, 960),
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
# 공개 스튜디오의 SFW 차단은 입력 차단어 게이트 한 겹이다(경량 백스톱 — 완벽한 차단은
# 아니고 명백한 성적/노출 요청을 걸러낸다).
#
# 과거엔 여기에 '디퓨전 네거티브'(SFW_NEGATIVE) 한 겹이 더 있었으나 txt2img 모델을
# Krea2-Turbo 로 옮기며 제거했다 — 증류 turbo 라 cfg=1.0 에서 돌아가고, cfg=1.0 이면
# 샘플러가 uncond 를 아예 건너뛰므로 네거티브 프롬프트는 원리적으로 무시된다.
# 되살리려면 cfg>1 이 필요한데 그건 turbo 스펙 밖이라 화질이 붕괴한다.

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
        # Lightning 4스텝 LoRA 를 끼운 편집 그래프(2026-09-14). 구 edit.json 은 env 로 되돌릴 때 쓴다.
        "edit_workflow": os.environ.get("COMFYUI_EDIT_WORKFLOW") or _pkg_workflow("edit_lightning.json"),
        "ckpt": os.environ.get("COMFYUI_CKPT") or "krea2_turbo-Q8_0.gguf",
        "edit_ckpt": os.environ.get("COMFYUI_EDIT_CKPT") or "qwen-image-edit-2511-Q4_K_M.gguf",
        # Krea2 텍스트 인코더 = Qwen3-VL-4B 단일(CLIPLoader type="krea2"). FLUX 시절의
        # T5+clip_l 2중 인코더(DualCLIPLoaderGGUF)는 이 아키텍처에 없다.
        "te": os.environ.get("COMFYUI_TE") or "qwen3vl_4b_fp8_scaled.safetensors",
        # 생성·편집이 같은 VAE(qwen_image)를 쓴다 — FLUX 의 ae.safetensors 는 더 이상 안 쓴다.
        "vae": os.environ.get("COMFYUI_VAE") or "qwen_image_vae.safetensors",
        "nsfw_lora": os.environ.get("COMFYUI_NSFW_LORA") or "qwen-image-edit-plus-nsfw-lora.safetensors",
        "nsfw_lora_weight": float(os.environ.get("COMFYUI_NSFW_LORA_WEIGHT") or "0.9"),
        # 레퍼런스+대상 2-이미지 편집(Qwen-Image-Edit-Plus: image1=대상·image2=레퍼런스).
        "edit_ref_workflow": os.environ.get("COMFYUI_EDIT_REF_WORKFLOW") or _pkg_workflow("edit_ref_lightning.json"),
        "edit_ref_ckpt": os.environ.get("COMFYUI_EDIT_REF_CKPT") or "qwen-image-edit-2511-Q4_K_M.gguf",
    }


def llm_config():
    """프롬프트 확장용 OpenAI-호환 LLM 설정. base_url 미설정이면 enabled=False(확장 폴백).

    기본값 = 공용 로컬 LLM(llamaserver.service :11434). 예전엔 env 가 없으면 그냥 꺼져서,
    systemd 로 뜬 프로덕션(env 없음·dotenv 없음)에선 확장이 조용히 안 돌았다.
    끄려면 IMAGE_PROMPT_LLM_BASE_URL=off.
    """
    base = (os.environ.get("IMAGE_PROMPT_LLM_BASE_URL")
            or os.environ.get("LOCAL_LLM_BASE_URL")
            or "http://127.0.0.1:11434/v1").rstrip("/")
    if base.lower() in ("off", "0", "none", "false"):
        base = ""
    return {
        "enabled": bool(base),
        "base_url": base,
        "api_key": os.environ.get("IMAGE_PROMPT_LLM_API_KEY") or os.environ.get("LOCAL_LLM_API_KEY") or "local",
        "model": (os.environ.get("IMAGE_PROMPT_LLM_MODEL") or os.environ.get("LOCAL_LLM_MODEL")
                  or "qwen3.6-35b-a3b-uncensored"),
        # 추론 OFF 로 부르므로(media/llm.py) 확장은 수 초면 끝난다. 그래도 안 오면
        # expand_prompt 가 원문으로 폴백한다 — 생성 자체는 안 막힌다.
        "timeout": int(os.environ.get("IMAGE_PROMPT_LLM_TIMEOUT") or "120"),
    }
