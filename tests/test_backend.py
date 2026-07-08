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
    assert cfg["frames"] == 97
    assert cfg["fps"] == 24


def test_sfw_violation_flags_explicit_terms():
    assert backend.sfw_violation("a nude woman on the beach")
    assert backend.sfw_violation("explicit porn scene")
    assert backend.sfw_violation("누드 화보")
    assert backend.sfw_violation("야한 그림 그려줘")
    # 영어는 대소문자 무관
    assert backend.sfw_violation("NAKED body")


def test_sfw_violation_allows_clean_prompts():
    assert backend.sfw_violation("a cat sitting on a sofa") is None
    assert backend.sfw_violation("노을 지는 해변 풍경") is None
    assert backend.sfw_violation("") is None
    assert backend.sfw_violation(None) is None


def test_sfw_violation_no_substring_false_positives():
    # 단어경계 매칭 — 흔한 단어 속 부분문자열은 통과해야 한다.
    assert backend.sfw_violation("data analysis dashboard") is None   # 'anal'
    assert backend.sfw_violation("the county of Sussex, England") is None  # 'sex'
    assert backend.sfw_violation("a document about cucumbers") is None     # 'cum'


def test_sfw_negative_is_nonempty_string():
    assert isinstance(backend.SFW_NEGATIVE, str) and "nude" in backend.SFW_NEGATIVE


def test_llm_config_enabled_flag_follows_base_url(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("IMAGE_PROMPT_LLM_BASE_URL", raising=False)
    assert backend.llm_config()["enabled"] is False
    monkeypatch.setenv("IMAGE_PROMPT_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    cfg = backend.llm_config()
    assert cfg["enabled"] is True
    assert cfg["base_url"] == "http://127.0.0.1:11434/v1"
