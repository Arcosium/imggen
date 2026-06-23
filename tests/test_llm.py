import json

from media import llm


def test_expand_returns_raw_when_llm_disabled(monkeypatch):
    monkeypatch.delenv("IMAGE_PROMPT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    assert llm.expand_prompt("a cat") == "a cat"


def test_expand_calls_llm_when_enabled(monkeypatch):
    monkeypatch.setenv("IMAGE_PROMPT_LLM_BASE_URL", "http://x:11434/v1")

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "  a photoreal cat, cinematic  "}}]}).encode()

    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout=0: _Resp())
    out = llm.expand_prompt("a cat")
    assert out == "a photoreal cat, cinematic"


def test_expand_falls_back_to_raw_on_error(monkeypatch):
    monkeypatch.setenv("IMAGE_PROMPT_LLM_BASE_URL", "http://x:11434/v1")

    def _boom(req, timeout=0):
        raise OSError("refused")

    monkeypatch.setattr(llm.urllib.request, "urlopen", _boom)
    assert llm.expand_prompt("a cat") == "a cat"
