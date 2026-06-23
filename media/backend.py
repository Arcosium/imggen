"""미디어 생성 백엔드 설정의 단일 소스.

env 미설정 시 모든 값이 로컬 ComfyUI 기본값(127.0.0.1:8188)으로 떨어진다.
이 모듈은 Gradio/파이프라인을 import하지 않는다(순환 방지). 모델 체크포인트 이름은
여기(운영자 대상 설정)에 모이며, 사용자 UI엔 절대 노출되지 않는다.
"""
import os

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
        "edit_ckpt": os.environ.get("COMFYUI_EDIT_CKPT") or "Qwen-Image-Edit-2511-Q8_0.gguf",
        "t5": os.environ.get("COMFYUI_T5") or "t5xxl_fp8_e4m3fn.safetensors",
        "clip_l": os.environ.get("COMFYUI_CLIP_L") or "clip_l.safetensors",
        "vae": os.environ.get("COMFYUI_VAE") or "ae.safetensors",
        "nsfw_lora": os.environ.get("COMFYUI_NSFW_LORA") or "qwen-image-edit-plus-nsfw-lora.safetensors",
        "nsfw_lora_weight": float(os.environ.get("COMFYUI_NSFW_LORA_WEIGHT") or "0.9"),
    }


def video_config():
    return {
        "base_url": _base_url(),
        "i2v_workflow": os.environ.get("COMFYUI_I2V_WORKFLOW") or _pkg_workflow("i2v.json"),
        "video_ckpt": os.environ.get("COMFYUI_VIDEO_MODEL") or "10Eros_v1-Q4_K_M.gguf",
        "t5": os.environ.get("COMFYUI_T5") or "t5xxl_fp8_e4m3fn.safetensors",
        "vae": os.environ.get("COMFYUI_VAE") or "ae.safetensors",
        "frames": int(os.environ.get("COMFYUI_VIDEO_FRAMES") or "49"),
        "fps": int(os.environ.get("COMFYUI_VIDEO_FPS") or "16"),
        "steps": int(os.environ.get("COMFYUI_VIDEO_STEPS") or "20"),
        "cfg": float(os.environ.get("COMFYUI_VIDEO_CFG") or "6.0"),
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
        "timeout": int(os.environ.get("IMAGE_PROMPT_LLM_TIMEOUT") or "30"),
    }
