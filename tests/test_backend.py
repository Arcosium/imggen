import importlib

from media import backend


def test_aspect_dims_known():
    assert backend.aspect_dims("9:16") == (720, 1280)
    assert backend.aspect_dims("16:9") == (1280, 720)
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


def test_image_config_defaults_are_krea2_models():
    """생성=Krea2-Turbo(단일 Qwen3-VL 인코더), 편집=Qwen-Image-Edit. 둘이 같은 VAE 를 쓴다."""
    cfg = backend.image_config()
    assert cfg["ckpt"] == "krea2_turbo-Q8_0.gguf"
    assert cfg["te"] == "qwen3vl_4b_fp8_scaled.safetensors"
    assert cfg["vae"] == "qwen_image_vae.safetensors"
    assert "t5" not in cfg and "clip_l" not in cfg   # FLUX 2중 인코더 잔재 금지


def test_backend_exposes_no_video_config():
    """영상 기능 전면 제거(2026-07-09) — 재도입 방지 회귀 테스트."""
    assert not hasattr(backend, "video_config")


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


def test_no_diffusion_negative_after_krea2_migration():
    """Krea2-Turbo 이관(2026-07-12)으로 SFW 방어선은 '입력 차단어 게이트' 한 겹이 됐다 —
    cfg=1.0 에선 샘플러가 uncond 를 건너뛰어 디퓨전 네거티브가 원리적으로 무시되기 때문.
    죽은 네거티브가 되살아나면 '막고 있다'는 착각만 준다(사장님 결정)."""
    assert not hasattr(backend, "SFW_NEGATIVE")


def test_llm_config_enabled_flag_follows_base_url(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("IMAGE_PROMPT_LLM_BASE_URL", raising=False)
    assert backend.llm_config()["enabled"] is False
    monkeypatch.setenv("IMAGE_PROMPT_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    cfg = backend.llm_config()
    assert cfg["enabled"] is True
    assert cfg["base_url"] == "http://127.0.0.1:11434/v1"
