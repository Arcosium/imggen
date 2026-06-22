"""ArcAI.ve-style fixed local ComfyUI image pipeline.

The UI never selects a model.  SFW/NSFW only changes the edit LoRA weight;
the server-side feature flag must also be enabled before NSFW is honoured.
"""
import base64
import json
import os
import time
import urllib.parse
import urllib.request
import uuid

COMFYUI_BASE_URL = os.environ.get("COMFYUI_BASE_URL", "http://127.0.0.1:8188").rstrip("/")
TXT2IMG_WORKFLOW = os.environ.get("COMFYUI_TXT2IMG_WORKFLOW", "")
EDIT_WORKFLOW = os.environ.get("COMFYUI_EDIT_WORKFLOW", "")
NSFW_LORA = os.environ.get("COMFYUI_NSFW_LORA", "qwen-image-edit-plus-nsfw-lora.safetensors")
NSFW_LORA_WEIGHT = float(os.environ.get("COMFYUI_NSFW_LORA_WEIGHT", "0.9"))
ASPECTS = {"1:1": (1024, 1024), "9:16": (576, 1024), "16:9": (1024, 576), "3:4": (768, 1024), "4:3": (1024, 768)}

def nsfw_enabled(requested: bool) -> bool:
    return requested and os.environ.get("IMAGE_NSFW_ENABLED", "0").lower() in {"1", "true", "yes", "on"}

def _json(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())

def _workflow(path, replacements):
    if not path:
        raise RuntimeError("ComfyUI workflow path is not configured")
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    for key, value in replacements.items():
        raw = raw.replace(key, str(value))
    return json.loads(raw)

def _run(workflow):
    prompt_id = _json(COMFYUI_BASE_URL + "/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())})["prompt_id"]
    for _ in range(120):
        time.sleep(1)
        history = _json(COMFYUI_BASE_URL + "/history/" + prompt_id)
        item = history.get(prompt_id)
        if not item:
            continue
        for node in item.get("outputs", {}).values():
            images = node.get("images", [])
            if images:
                image = images[0]
                query = urllib.parse.urlencode({"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")})
                with urllib.request.urlopen(COMFYUI_BASE_URL + "/view?" + query, timeout=120) as r:
                    return r.read()
    raise TimeoutError("ComfyUI generation timed out")

def generate(prompt, aspect, *, nsfw=False):
    width, height = ASPECTS.get(aspect, ASPECTS["1:1"])
    return _run(_workflow(TXT2IMG_WORKFLOW, {"%POSITIVE%": prompt, "%NEGATIVE%": "", "%WIDTH%": width, "%HEIGHT%": height, "%SEED%": 0, "%STEPS%": 24, "%CFG%": 3.5, "%CKPT%": "FHDR_ComfyUI-Q8_0.gguf", "%T5%": "t5xxl_fp8_e4m3fn.safetensors", "%CLIP_L%": "clip_l.safetensors", "%VAE%": "ae.safetensors"}))

def edit(image_bytes, prompt, *, nsfw=False):
    boundary = "----ImageStudio" + uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"input.png\"\r\nContent-Type: image/png\r\n\r\n").encode() + image_bytes + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(COMFYUI_BASE_URL + "/upload/image", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        name = json.loads(r.read())["name"]
    weight = NSFW_LORA_WEIGHT if nsfw_enabled(nsfw) else 0.0
    return _run(_workflow(EDIT_WORKFLOW, {"%POSITIVE%": prompt, "%INPUT_IMAGE%": name, "%SEED%": 0, "%STEPS%": 20, "%CFG%": 4.0, "%DENOISE%": 0.7, "%EDIT_CKPT%": "Qwen-Image-Edit-2511-Q8_0.gguf", "%LORA_NAME%": NSFW_LORA, "%LORA_WEIGHT%": weight}))
