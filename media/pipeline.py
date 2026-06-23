"""로컬 미디어 파이프라인: expand(LLM) → txt2img → edit → img2video.

SFW/NSFW 는 mode 한 값으로 갈림 — edit 단계 NSFW LoRA weight 만 0↔N 스위치.
단계 사이 free_memory 로 모델 언로드(피크 1모델). on_stage(stage) 콜백으로 진행 신호:
expand/txt2img/edit/img2video/done. make_video 는 input_image 가 있으면 i2v 직행.
"""
from media import backend, comfyui, llm


def _run_image(graph, base_url):
    pid = comfyui.queue_prompt(base_url, graph)
    outputs = comfyui.poll_history(base_url, pid)
    return comfyui.fetch_media(base_url, comfyui.first_image_ref(outputs))


def txt2img(prompt, *, aspect="1:1", seed=0, steps=24, cfg=3.5):
    ic = backend.image_config()
    w, h = backend.aspect_dims(aspect)
    graph = comfyui.fill_template(comfyui.load_template(ic["txt2img_workflow"]), {
        "%POSITIVE%": prompt, "%NEGATIVE%": "", "%WIDTH%": w, "%HEIGHT%": h,
        "%SEED%": seed, "%STEPS%": steps, "%CFG%": cfg,
        "%CKPT%": ic["ckpt"], "%T5%": ic["t5"], "%CLIP_L%": ic["clip_l"], "%VAE%": ic["vae"],
    })
    return _run_image(graph, ic["base_url"])


def edit_image(image_bytes, instructions, *, mode="sfw", seed=0, steps=20, cfg=4.0, denoise=0.7):
    ic = backend.image_config()
    weight = ic["nsfw_lora_weight"] if mode == "uncensored" else 0.0
    name = comfyui.upload_image(ic["base_url"], image_bytes)["name"]
    graph = comfyui.fill_template(comfyui.load_template(ic["edit_workflow"]), {
        "%POSITIVE%": instructions, "%INPUT_IMAGE%": name, "%SEED%": seed,
        "%STEPS%": steps, "%CFG%": cfg, "%DENOISE%": denoise,
        "%EDIT_CKPT%": ic["edit_ckpt"], "%LORA_NAME%": ic["nsfw_lora"], "%LORA_WEIGHT%": weight,
    })
    return _run_image(graph, ic["base_url"])


def img2video(image_bytes, prompt, *, aspect="9:16", negative="", seed=0):
    vc = backend.video_config()
    w, h = backend.aspect_dims(aspect)
    name = comfyui.upload_image(vc["base_url"], image_bytes)["name"]
    graph = comfyui.fill_template(comfyui.load_template(vc["i2v_workflow"]), {
        "%POSITIVE%": prompt, "%NEGATIVE%": negative, "%INPUT_IMAGE%": name,
        "%WIDTH%": w, "%HEIGHT%": h, "%FRAMES%": vc["frames"], "%FPS%": vc["fps"],
        "%SEED%": seed, "%STEPS%": vc["steps"], "%CFG%": vc["cfg"],
        "%VIDEO_CKPT%": vc["video_ckpt"], "%T5%": vc["t5"], "%VAE%": vc["vae"],
    })
    pid = comfyui.queue_prompt(vc["base_url"], graph)
    outputs = comfyui.poll_history(vc["base_url"], pid, timeout=900)
    ref = comfyui.first_media_ref(outputs)
    data = comfyui.fetch_media(vc["base_url"], ref)
    mime = "video/mp4" if ref["filename"].lower().endswith(".mp4") else "video/webm"
    return data, mime


def _resolve_prompt(idea, prompt, aspect, expand):
    if prompt and prompt.strip():
        return prompt
    if expand:
        return llm.expand_prompt(idea or "", aspect=aspect)
    return idea or ""


def make_image(*, idea=None, prompt=None, aspect="1:1", mode="sfw",
               edit_instructions=None, expand=True, on_stage=None):
    def _stage(s):
        if on_stage:
            on_stage(s)
    base_url = backend.image_config()["base_url"]
    if expand and not (prompt and prompt.strip()):
        _stage("expand")
    used = _resolve_prompt(idea, prompt, aspect, expand)
    _stage("txt2img")
    img = txt2img(used, aspect=aspect)
    if edit_instructions or mode == "uncensored":
        comfyui.free_memory(base_url)
        _stage("edit")
        img = edit_image(img, edit_instructions or "enhance and refine, keep composition", mode=mode)
    _stage("done")
    return {"image": img, "prompt_used": used}


def make_video(*, idea=None, prompt=None, aspect="9:16", mode="sfw",
               edit_instructions=None, input_image=None, expand=True, on_stage=None):
    def _stage(s):
        if on_stage:
            on_stage(s)
    base_url = backend.image_config()["base_url"]

    # 이미지→영상: 사용자 이미지를 바로 애니메이트(생성 단계 생략)
    if input_image is not None:
        used = prompt or (idea or "")
        _stage("img2video")
        video, mime = img2video(input_image, used, aspect=aspect)
        _stage("done")
        return {"video": video, "mime": mime, "base_image": None,
                "edited_image": None, "prompt_used": used}

    # 텍스트→영상: expand → txt2img → (조건부 edit) → img2video
    if expand and not (prompt and prompt.strip()):
        _stage("expand")
    used = _resolve_prompt(idea, prompt, aspect, expand)
    _stage("txt2img")
    base = txt2img(used, aspect=aspect)
    comfyui.free_memory(base_url)
    edited = None
    src = base
    if edit_instructions or mode == "uncensored":
        _stage("edit")
        edited = edit_image(base, edit_instructions or "enhance and refine, keep composition", mode=mode)
        src = edited
        comfyui.free_memory(base_url)
    _stage("img2video")
    video, mime = img2video(src, used, aspect=aspect)
    comfyui.free_memory(base_url)
    _stage("done")
    return {"video": video, "mime": mime, "base_image": base,
            "edited_image": edited, "prompt_used": used}
