"""로컬 미디어 파이프라인: expand(LLM) → txt2img → edit → img2video.

SFW/NSFW 는 mode 한 값으로 갈림 — edit 단계 NSFW LoRA weight 만 0↔N 스위치.
단계 사이 free_memory 로 모델 언로드(피크 1모델). on_stage(stage) 콜백으로 진행 신호:
expand/txt2img/edit/img2video/done. make_video 는 input_image 가 있으면 i2v 직행.
"""
from media import backend, comfyui, llm


def _run_image(graph, base_url, timeout=900):
    # 로컬 GPU(GB10)에서 FLUX/Qwen-Edit 1장이 수 분 걸린다 — 기본 300s 로는 부족해 타임아웃.
    pid = comfyui.queue_prompt(base_url, graph)
    outputs = comfyui.poll_history(base_url, pid, timeout=timeout)
    return comfyui.fetch_media(base_url, comfyui.first_image_ref(outputs))


def txt2img(prompt, *, aspect="1:1", seed=0, steps=24, cfg=3.5, negative=None):
    ic = backend.image_config()
    w, h = backend.aspect_dims(aspect)
    neg = backend.SFW_NEGATIVE if negative is None else negative
    graph = comfyui.fill_template(comfyui.load_template(ic["txt2img_workflow"]), {
        "%POSITIVE%": prompt, "%NEGATIVE%": neg, "%WIDTH%": w, "%HEIGHT%": h,
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


def edit_image_ref(target_bytes, reference_bytes, instructions, *, mode="sfw",
                   composite=False, seed=0, steps=10, cfg=4.0, denoise=1.0):
    """레퍼런스+대상 2-이미지 편집(Qwen-Image-Edit-Plus: image1=대상, image2=레퍼런스).
    composite=False(분위기 이식): 레퍼런스의 조명·색감·무드를 대상에 입힘(피사체/구도 보존).
    composite=True(장면 합성): 대상의 피사체/제품을 레퍼런스 장면 안에 합성.
    비전 LLM 불필요 — 모델이 두 이미지를 직접 보고 지시(directive)대로 처리한다."""
    ic = backend.image_config()
    weight = ic["nsfw_lora_weight"] if mode == "uncensored" else 0.0
    instr = (instructions or "").strip()
    if composite:
        directive = ("Place the main subject/product from the first image into the scene, background, "
                     "setting and lighting of the second reference image. Preserve the first subject's "
                     "identity, shape, colors and details; blend it in naturally and realistically. "
                     + instr).strip()
    else:
        directive = ("Restyle the first image to match the mood, lighting, color palette, texture and "
                     "overall aesthetic of the second reference image. Keep the first image's subject, "
                     "composition and identity intact. " + instr).strip()
    tname = comfyui.upload_image(ic["base_url"], target_bytes)["name"]
    rname = comfyui.upload_image(ic["base_url"], reference_bytes)["name"]
    graph = comfyui.fill_template(comfyui.load_template(ic["edit_ref_workflow"]), {
        "%POSITIVE%": directive, "%INPUT_IMAGE%": tname, "%REF_IMAGE%": rname,
        "%SEED%": seed, "%STEPS%": steps, "%CFG%": cfg, "%DENOISE%": denoise,
        "%EDIT_CKPT%": ic["edit_ref_ckpt"], "%LORA_NAME%": ic["nsfw_lora"], "%LORA_WEIGHT%": weight,
    })
    return _run_image(graph, ic["base_url"])


def _video_first_frame(video_bytes, *, at=0.5):
    """V2V 입력 영상에서 대표 프레임 1장(PNG bytes) 추출(ffmpeg). 짧은 영상은 첫 프레임 폴백."""
    import subprocess
    import tempfile
    import os as _os
    vf = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    try:
        vf.write(video_bytes)
        vf.flush()
        vf.close()
        opath = vf.name + ".png"
        try:
            subprocess.run(["ffmpeg", "-y", "-ss", str(at), "-i", vf.name, "-frames:v", "1", opath],
                           check=True, capture_output=True, timeout=60)
        except Exception:
            subprocess.run(["ffmpeg", "-y", "-i", vf.name, "-frames:v", "1", opath],
                           check=True, capture_output=True, timeout=60)
        with open(opath, "rb") as f:
            return f.read()
    finally:
        for p in (vf.name, vf.name + ".png"):
            try:
                _os.remove(p)
            except Exception:
                pass


def img2video(image_bytes, prompt, *, aspect="9:16", negative=None, seed=0):
    vc = backend.video_config()
    w, h = backend.aspect_dims(aspect)
    neg = backend.SFW_NEGATIVE if negative is None else negative
    name = comfyui.upload_image(vc["base_url"], image_bytes)["name"]
    graph = comfyui.fill_template(comfyui.load_template(vc["i2v_workflow"]), {
        "%POSITIVE%": prompt, "%NEGATIVE%": neg, "%INPUT_IMAGE%": name,
        "%WIDTH%": w, "%HEIGHT%": h, "%FRAMES%": vc["frames"], "%FPS%": vc["fps"],
        "%SEED%": seed, "%STEPS%": vc["steps"], "%CFG%": vc["cfg"],
        "%VIDEO_CKPT%": vc["video_ckpt"], "%T5%": vc["t5"], "%VAE%": vc["vae"],
    })
    pid = comfyui.queue_prompt(vc["base_url"], graph)
    # GB10에서 기본 영상(576x1024 x 49프레임 LTX-2.3)은 수십 분 걸릴 수 있어 900s 로는 부족.
    outputs = comfyui.poll_history(vc["base_url"], pid, timeout=1800)
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
        comfyui.free_memory(base_url)
    _stage("done")
    return {"image": img, "prompt_used": used}


def make_video(*, idea=None, prompt=None, aspect="9:16", mode="sfw",
               edit_instructions=None, input_image=None, source_video=None,
               expand=True, on_stage=None):
    def _stage(s):
        if on_stage:
            on_stage(s)
    base_url = backend.image_config()["base_url"]

    # 영상→영상(V2V): 입력 영상의 대표 프레임을 뽑아 (선택)편집 후 재애니메이트해 재구성
    if source_video is not None:
        _stage("expand")
        frame = _video_first_frame(source_video)
        base = frame
        edited = None
        if edit_instructions or (prompt and prompt.strip()):
            _stage("edit")
            base = edit_image(frame, edit_instructions or prompt, mode=mode)
            edited = base
            comfyui.free_memory(base_url)
        used = prompt or idea or ""
        _stage("img2video")
        video, mime = img2video(base, used, aspect=aspect)
        comfyui.free_memory(base_url)
        _stage("done")
        return {"video": video, "mime": mime, "base_image": frame,
                "edited_image": edited, "prompt_used": used}

    # 이미지→영상: 사용자 이미지를 애니메이트. edit_instructions 있으면 먼저 편집 후 영상(편집+영상),
    # 없으면 모션만(편집 생략).
    if input_image is not None:
        base = input_image
        edited = None
        if edit_instructions:
            _stage("edit")
            base = edit_image(input_image, edit_instructions, mode=mode)
            edited = base
            comfyui.free_memory(base_url)
        used = prompt or (idea or "")
        _stage("img2video")
        video, mime = img2video(base, used, aspect=aspect)
        comfyui.free_memory(base_url)
        _stage("done")
        return {"video": video, "mime": mime, "base_image": input_image,
                "edited_image": edited, "prompt_used": used}

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
