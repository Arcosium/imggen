import json

from media import backend, comfyui


def test_txt2img_template_fills_all_tokens():
    cfg = backend.image_config()
    graph = comfyui.fill_template(comfyui.load_template(cfg["txt2img_workflow"]), {
        "%POSITIVE%": "a cat", "%NEGATIVE%": "", "%WIDTH%": 576, "%HEIGHT%": 1024,
        "%SEED%": 0, "%STEPS%": 24, "%CFG%": 3.5, "%CKPT%": cfg["ckpt"],
        "%T5%": cfg["t5"], "%CLIP_L%": cfg["clip_l"], "%VAE%": cfg["vae"],
    })
    blob = json.dumps(graph)
    assert "%" not in blob  # 모든 토큰 치환됨
    assert graph["14"]["inputs"]["width"] == 576  # 단독 토큰 int 보존


def test_i2v_template_has_video_combine_node():
    cfg = backend.video_config()
    tpl = comfyui.load_template(cfg["i2v_workflow"])
    classes = {n["class_type"] for n in tpl.values()}
    assert "VHS_VideoCombine" in classes
    assert "LTXVImgToVideo" in classes   # 영상 백엔드는 WAN → LTX-Video 로 이관됨


def test_edit_template_has_lora_weight_token():
    cfg = backend.image_config()
    raw = json.dumps(comfyui.load_template(cfg["edit_workflow"]))
    assert "%LORA_WEIGHT%" in raw
    assert "%INPUT_IMAGE%" in raw
