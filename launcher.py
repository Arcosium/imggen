"""PyInstaller .exe entry point.
app.py를 전혀 수정하지 않고:
  1) BASE_DIR 이 .exe 위치로 잡히도록 래핑
  2) gradio_client 의 알려진 schema 분석 버그를 monkey-patch 로 우회
"""
import os
import sys


# ===== gradio_client 의 schema-bool 버그 우회 =====
# 증상: TypeError: argument of type 'bool' is not iterable
# 원인: JSON schema 의 additionalProperties 가 True/False (bool) 일 때
#       gradio_client.utils.get_type / _json_schema_to_python_type 가 dict 만 가정함
def _patch_gradio_client():
    try:
        from gradio_client import utils as gc_utils
    except ImportError:
        return

    if hasattr(gc_utils, "get_type"):
        _orig_gt = gc_utils.get_type

        def _safe_get_type(schema):
            if not isinstance(schema, dict):
                return "Any"
            try:
                return _orig_gt(schema)
            except Exception:
                return "Any"

        gc_utils.get_type = _safe_get_type

    if hasattr(gc_utils, "_json_schema_to_python_type"):
        _orig_j = gc_utils._json_schema_to_python_type

        def _safe_json(schema, defs=None):
            if not isinstance(schema, dict):
                return "Any"
            try:
                return _orig_j(schema, defs)
            except Exception:
                return "Any"

        gc_utils._json_schema_to_python_type = _safe_json

    if hasattr(gc_utils, "json_schema_to_python_type"):
        _orig_j2 = gc_utils.json_schema_to_python_type

        def _safe_json2(schema):
            try:
                return _orig_j2(schema)
            except Exception:
                return "Any"

        gc_utils.json_schema_to_python_type = _safe_json2


_patch_gradio_client()


# ===== BASE_DIR 위장 후 app.py 실행 =====
if getattr(sys, "frozen", False):
    EXE_DIR = os.path.dirname(sys.executable)
else:
    EXE_DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(EXE_DIR)

# 번들 내부의 app.py 위치
if hasattr(sys, "_MEIPASS"):
    app_path = os.path.join(sys._MEIPASS, "app.py")
else:
    app_path = os.path.join(EXE_DIR, "app.py")

# app.py를 __main__ 으로 실행하되 __file__ 은 EXE_DIR/app.py 로 위장
# → 내부의 BASE_DIR = os.path.dirname(os.path.abspath(__file__)) 가 EXE_DIR 로 해석됨
init_globals = {
    "__name__": "__main__",
    "__file__": os.path.join(EXE_DIR, "app.py"),
    "__builtins__": __builtins__,
}

with open(app_path, "r", encoding="utf-8") as f:
    source = f.read()

code = compile(source, os.path.join(EXE_DIR, "app.py"), "exec")
exec(code, init_globals)
