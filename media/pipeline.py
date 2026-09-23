"""로컬 이미지 파이프라인: expand(LLM) → txt2img → edit.

SFW/NSFW 는 mode 한 값으로 갈림 — edit 단계 NSFW LoRA weight 만 0↔N 스위치.
단계 사이 free_memory 로 모델 언로드(피크 1모델). on_stage(stage) 콜백으로 진행 신호:
expand/txt2img/edit/done.
"""
import random

from media import backend, comfyui, llm


def _seed(seed):
    # 시드를 안 주면 매번 새로 뽑는다. 예전엔 0 고정이라 다듬기를 끈 N장 생성이 같은 그림 N장이었다(2026-09-23).
    return random.randrange(2**32) if seed is None else seed


def _run_image(graph, base_url, timeout=1800):
    # 로컬 GPU(GB10)에서 Qwen-Image 2.1 UC Q8 은 1024² 한 장에 약 470초(2026-09-23 실측, GGUF 역양자화 비용).
    # 쇼츠 작업이 앞에 있거나 메모리 입장 대기가 붙으면 더 걸린다 — 900초로는 모자라 1800초로 둔다.
    pid = comfyui.queue_prompt(base_url, graph)
    outputs = comfyui.poll_history(base_url, pid, timeout=timeout)
    return comfyui.fetch_media(base_url, comfyui.first_image_ref(outputs))


# 2026-09-23: 생성·편집 = Qwen-Image 2.1 UC(검열 해제판) 하나. 공식 ComfyUI 시작값 Euler/simple 25스텝·CFG 1.
# cfg=1.0 에선 uncond 를 건너뛰므로 네거티브 프롬프트는 성립하지 않는다. 모델에 SFW/NSFW 구분이 없으므로
# SFW 방어선은 입력 차단어 게이트(backend.sfw_violation) 한 겹이다. %LORA_*% 는 env 로 옛 Edit-2511
# 그래프로 되돌릴 때만 쓰인다.
QWEN21_STEPS = 25


def txt2img(prompt, *, aspect="1:1", seed=None, steps=QWEN21_STEPS, cfg=1.0):
    ic = backend.image_config()
    w, h = backend.aspect_dims(aspect)
    graph = comfyui.fill_template(comfyui.load_template(ic["txt2img_workflow"]), {
        "%POSITIVE%": prompt, "%WIDTH%": w, "%HEIGHT%": h,
        "%SEED%": _seed(seed), "%STEPS%": steps, "%CFG%": cfg,
        "%CKPT%": ic["ckpt"], "%TE%": ic["te"], "%VAE%": ic["vae"],
    })
    return _run_image(graph, ic["base_url"])


# denoise 는 1.0 이어야 한다: 구조 보존은 conditioning(image_1)이 맡고, 0.7 이면 지시가 안 먹었다(9/14 실측).
def edit_image(image_bytes, instructions, *, mode="sfw", seed=None, steps=QWEN21_STEPS, cfg=1.0, denoise=1.0):
    ic = backend.image_config()
    weight = ic["nsfw_lora_weight"] if mode == "uncensored" else 0.0
    name = comfyui.upload_image(ic["base_url"], image_bytes)["name"]
    graph = comfyui.fill_template(comfyui.load_template(ic["edit_workflow"]), {
        "%POSITIVE%": instructions, "%INPUT_IMAGE%": name, "%SEED%": _seed(seed),
        "%STEPS%": steps, "%CFG%": cfg, "%DENOISE%": denoise,
        "%EDIT_CKPT%": ic["edit_ckpt"], "%LORA_NAME%": ic["nsfw_lora"], "%LORA_WEIGHT%": weight,
        "%CKPT%": ic["edit_ckpt"], "%TE%": ic["te"], "%VAE%": ic["vae"],
    })
    return _run_image(graph, ic["base_url"])


def edit_image_ref(target_bytes, reference_bytes, instructions, *, mode="sfw",
                   composite=False, seed=None, steps=QWEN21_STEPS, cfg=1.0, denoise=1.0):
    """레퍼런스+대상 2-이미지 편집(image_1=대상, image_2=레퍼런스).
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
        "%SEED%": _seed(seed), "%STEPS%": steps, "%CFG%": cfg, "%DENOISE%": denoise,
        "%EDIT_CKPT%": ic["edit_ref_ckpt"], "%LORA_NAME%": ic["nsfw_lora"], "%LORA_WEIGHT%": weight,
        "%CKPT%": ic["edit_ref_ckpt"], "%TE%": ic["te"], "%VAE%": ic["vae"],
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
    # 제한 해제 모드도 생성 한 번으로 끝낸다(2026-09-23). Krea2 시절엔 NSFW LoRA 를 끼운 편집 모델로
    # 한 번 더 돌려야 했지만, 지금 생성 모델(Qwen-Image 2.1 UC)은 자체가 무검열이라 그 단계는 장당 약 8분만 더 쓴다.
    if edit_instructions:
        comfyui.free_memory(base_url)
        _stage("edit")
        img = edit_image(img, edit_instructions or "enhance and refine, keep composition", mode=mode)
        comfyui.free_memory(base_url)
    _stage("done")
    return {"image": img, "prompt_used": used}
