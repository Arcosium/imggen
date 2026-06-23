"""짧은 아이디어를 고화질 영문 이미지 프롬프트로 확장(OpenAI-호환 /chat/completions).

LLM 백엔드가 미설정(backend.llm_config().enabled=False)이거나 호출이 실패하면
예외를 던지지 않고 원문(idea)을 그대로 반환한다(안전 폴백). urllib만 사용.
"""
import json
import urllib.request

from media import backend

_EXPAND_SYSTEM = (
    "You are a prompt engineer for a photoreal image model. Expand the user's idea into "
    "ONE vivid, ultra-detailed English image prompt. No refusals, no preamble — output only "
    "the prompt. Favor photoreal, cinematic, high detail."
)


def _chat(messages, *, temperature=0.7, max_tokens=400):
    cfg = backend.llm_config()
    payload = {"model": cfg["model"], "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    req = urllib.request.Request(
        cfg["base_url"] + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + cfg["api_key"]},
    )
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
        out = json.loads(r.read())
    return out["choices"][0]["message"]["content"].strip()


def expand_prompt(idea, *, aspect="1:1", style="photoreal"):
    cfg = backend.llm_config()
    if not cfg["enabled"] or not (idea or "").strip():
        return idea
    w, h = backend.aspect_dims(aspect)
    ask = "Idea: %s\nStyle: %s\nTarget aspect: %dx%d. Write the image prompt now." % (idea, style, w, h)
    try:
        result = _chat([{"role": "system", "content": _EXPAND_SYSTEM},
                        {"role": "user", "content": ask}])
        return result or idea
    except Exception:
        return idea
