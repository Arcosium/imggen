"""로컬 이미지 파이프라인: expand(LLM) → txt2img → edit.

SFW/NSFW 는 mode 한 값으로 갈림 — edit 단계 NSFW LoRA weight 만 0↔N 스위치.
단계 사이 free_memory 로 모델 언로드(피크 1모델). on_stage(stage) 콜백으로 진행 신호:
expand/txt2img/edit/done.
"""
from media import backend, comfyui, llm


def _run_image(graph, base_url, timeout=900):
    # 로컬 GPU(GB10)에서 Qwen-Edit 1장이 수 분 걸린다 — 기본 300s 로는 부족해 타임아웃.
    pid = comfyui.queue_prompt(base_url, graph)
    outputs = comfyui.poll_history(base_url, pid, timeout=timeout)
    return comfyui.fetch_media(base_url, comfyui.first_image_ref(outputs))


def txt2img(prompt, *, aspect="1:1", seed=0, steps=8, cfg=1.0):
    """Krea2-Turbo 텍스트→이미지. 증류 turbo 라 8스텝·cfg=1.0 이 스펙 —
    cfg=1.0 에선 uncond 를 건너뛰므로 네거티브 프롬프트 자체가 성립하지 않는다."""
    ic = backend.image_config()
    w, h = backend.aspect_dims(aspect)
    graph = comfyui.fill_template(comfyui.load_template(ic["txt2img_workflow"]), {
        "%POSITIVE%": prompt, "%WIDTH%": w, "%HEIGHT%": h,
        "%SEED%": seed, "%STEPS%": steps, "%CFG%": cfg,
        "%CKPT%": ic["ckpt"], "%TE%": ic["te"], "%VAE%": ic["vae"],
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
