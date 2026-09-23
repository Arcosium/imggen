import json

from media import backend, comfyui


def test_txt2img_template_fills_all_tokens():
    cfg = backend.image_config()
    graph = comfyui.fill_template(comfyui.load_template(cfg["txt2img_workflow"]), {
        "%POSITIVE%": "a cat", "%WIDTH%": 720, "%HEIGHT%": 1280,
        "%SEED%": 0, "%STEPS%": 25, "%CFG%": 1.0, "%CKPT%": cfg["ckpt"],
        "%TE%": cfg["te"], "%VAE%": cfg["vae"],
    })
    blob = json.dumps(graph)
    assert "%" not in blob  # 모든 토큰 치환됨
    assert graph["14"]["inputs"]["width"] == 720  # 단독 토큰 int 보존


def test_all_templates_use_qwen21_gguf():
    """2026-09-23: 생성·편집·레퍼런스 편집이 모두 Qwen-Image 2.1 UC GGUF 한 모델이다."""
    cfg = backend.image_config()
    for key in ("txt2img_workflow", "edit_workflow", "edit_ref_workflow"):
        g = comfyui.load_template(cfg[key])
        kinds = {n["class_type"] for n in g.values()}
        assert "UnetLoaderGGUF" in kinds and "TextEncodeQwenImage21" in kinds, key
        assert "LoraLoaderModelOnly" not in kinds and "UNETLoader" not in kinds, key
        filled = comfyui.fill_template(g, {
            "%POSITIVE%": "x", "%WIDTH%": 1, "%HEIGHT%": 1, "%SEED%": 1, "%STEPS%": 25, "%CFG%": 1.0,
            "%DENOISE%": 1.0, "%INPUT_IMAGE%": "a.png", "%REF_IMAGE%": "b.png",
            "%CKPT%": cfg["ckpt"], "%TE%": cfg["te"], "%VAE%": cfg["vae"]})
        assert "%" not in json.dumps(filled), key


def test_edit_image_defaults_full_denoise():
    """CFG 1·denoise 1.0 — denoise 0.7 이면 편집 지시가 안 먹어 원본이 그대로 나온다(2026-09-14 실측)."""
    import inspect
    from media import pipeline
    d = {k: v.default for k, v in inspect.signature(pipeline.edit_image).parameters.items()}
    assert (d["steps"], d["cfg"], d["denoise"]) == (pipeline.QWEN21_STEPS, 1.0, 1.0)
