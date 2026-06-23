import app


def test_build_ui_constructs_without_error():
    demo = app.build_ui()
    assert demo is not None


def test_ui_has_no_model_names_in_source():
    src = open("app.py", encoding="utf-8").read()
    banned = ["FLUX", "Qwen", "Veo", "Gemini", "Imagen", "ComfyUI", "Wan"]
    leaked = [w for w in banned if w in src]
    assert leaked == [], "모델명 누출: %s" % leaked
