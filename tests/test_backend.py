import importlib

from media import backend


def test_aspect_dims_known():
    assert backend.aspect_dims("9:16") == (576, 1024)
    assert backend.aspect_dims("16:9") == (1024, 576)
    assert backend.aspect_dims("1:1") == (1024, 1024)


def test_aspect_dims_unknown_falls_back_to_square():
    assert backend.aspect_dims("garbage") == (1024, 1024)
    assert backend.aspect_dims("") == (1024, 1024)
    assert backend.aspect_dims(None) == (1024, 1024)


def test_resolve_image_mode_downgrades_without_server_flag(monkeypatch):
    monkeypatch.delenv("IMAGE_NSFW_ENABLED", raising=False)
    assert backend.resolve_image_mode("uncensored") == "sfw"
    assert backend.resolve_image_mode("sfw") == "sfw"
    assert backend.resolve_image_mode(None) == "sfw"


def test_resolve_image_mode_honored_when_server_flag_on(monkeypatch):
    monkeypatch.setenv("IMAGE_NSFW_ENABLED", "1")
    assert backend.resolve_image_mode("uncensored") == "uncensored"
    assert backend.resolve_image_mode("sfw") == "sfw"


def test_image_config_defaults_point_to_packaged_workflows():
    cfg = backend.image_config()
    assert cfg["base_url"] == "http://127.0.0.1:8188"
    assert cfg["txt2img_workflow"].endswith("workflows/txt2img.json")
    assert cfg["edit_workflow"].endswith("workflows/edit.json")
    assert cfg["nsfw_lora_weight"] == 0.9


def test_video_config_defaults():
    cfg = backend.video_config()
    assert cfg["i2v_workflow"].endswith("workflows/i2v.json")
    assert cfg["frames"] == 49
    assert cfg["fps"] == 16


def test_llm_config_enabled_flag_follows_base_url(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("IMAGE_PROMPT_LLM_BASE_URL", raising=False)
    assert backend.llm_config()["enabled"] is False
    monkeypatch.setenv("IMAGE_PROMPT_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    cfg = backend.llm_config()
    assert cfg["enabled"] is True
    assert cfg["base_url"] == "http://127.0.0.1:11434/v1"
