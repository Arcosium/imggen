import json

from media import backend, comfyui


def test_txt2img_template_fills_all_tokens():
    cfg = backend.image_config()
    graph = comfyui.fill_template(comfyui.load_template(cfg["txt2img_workflow"]), {
        "%POSITIVE%": "a cat", "%WIDTH%": 720, "%HEIGHT%": 1280,
        "%SEED%": 0, "%STEPS%": 8, "%CFG%": 1.0, "%CKPT%": cfg["ckpt"],
        "%TE%": cfg["te"], "%VAE%": cfg["vae"],
    })
    blob = json.dumps(graph)
    assert "%" not in blob  # 모든 토큰 치환됨
    assert graph["14"]["inputs"]["width"] == 720  # 단독 토큰 int 보존


def test_txt2img_template_follows_krea2_turbo_spec():
    """Krea2-Turbo 는 증류 모델 — er_sde 샘플러에 cfg=1.0 으로 돈다. cfg=1.0 이면 샘플러가
    uncond 를 건너뛰므로 네거티브 프롬프트가 성립하지 않아, 네거티브 슬롯은
    ConditioningZeroOut 으로 채운다(텍스트 네거티브 노드가 있으면 안 된다)."""
    cfg = backend.image_config()
    graph = comfyui.load_template(cfg["txt2img_workflow"])
    assert graph["11"]["inputs"]["type"] == "krea2"
    assert graph["15"]["inputs"]["sampler_name"] == "er_sde"
    assert graph["18"]["class_type"] == "ConditioningZeroOut"
    assert graph["15"]["inputs"]["negative"] == ["18", 0]
    assert "%NEGATIVE%" not in json.dumps(graph)


def test_edit_template_has_lora_weight_token():
    cfg = backend.image_config()
    raw = json.dumps(comfyui.load_template(cfg["edit_workflow"]))
    assert "%LORA_WEIGHT%" in raw
    assert "%INPUT_IMAGE%" in raw


def test_edit_templates_chain_lightning_lora():
    """2026-09-14: 편집 그래프에 Lightning 4스텝 LoRA — Unet → Lightning → NSFW LoRA → KSampler."""
    cfg = backend.image_config()
    for key in ("edit_workflow", "edit_ref_workflow"):
        g = comfyui.load_template(cfg[key])
        assert g["40"]["inputs"]["lora_name"].startswith("Qwen-Image-Edit-2511-Lightning-4steps"), key
        assert g["40"]["inputs"]["model"] == ["20", 0] and g["21"]["inputs"]["model"] == ["40", 0], key
        assert g["25"]["inputs"]["model"] == ["21", 0], key


def test_edit_image_defaults_follow_lightning_and_full_denoise():
    """4스텝·CFG 1·denoise 1.0 — denoise 0.7 이면 편집 지시가 안 먹어 원본이 그대로 나온다(2026-09-14 실측)."""
    import inspect
    from media import pipeline
    d = {k: v.default for k, v in inspect.signature(pipeline.edit_image).parameters.items()}
    assert (d["steps"], d["cfg"], d["denoise"]) == (4, 1.0, 1.0)

