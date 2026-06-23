# Image & Video Studio — 로컬 미디어 생성 스튜디오

로컬 미디어 백엔드(ComfyUI)를 통해 이미지·영상을 생성하는 Gradio 데스크톱/서비스 앱.
사용자는 모델을 고르지 않으며, API 키 입력도 없습니다.

## 기능

### 🎨 이미지 스튜디오
- **텍스트 → 이미지**: 프롬프트만 입력
- **프롬프트 자동 다듬기**(기본 ON): 짧은 아이디어를 고화질 프롬프트로 확장. LLM 백엔드가 없으면 입력 그대로 사용(자동 폴백)
- **참조 이미지 편집**: 원본 이미지 + 편집 지시로 수정
- **비율**: 1:1 / 9:16 / 16:9 / 3:4 / 4:3

### 🎬 비디오 스튜디오
- **텍스트 → 영상**: 프롬프트로 이미지 생성 후 영상화까지 한 번에
- **이미지 → 영상**: 보유한 이미지를 올려 바로 영상화
- **비율**: 9:16 / 16:9 / 1:1

## 백엔드 설정 (ComfyUI)

앱이 도는 머신(또는 GPU 호스트)에서 ComfyUI를 실행하고 환경변수로 가리킵니다.

```env
COMFYUI_BASE_URL=http://127.0.0.1:8188

# (선택) 워크플로 경로 — 기본값은 media/workflows/*.json
# COMFYUI_TXT2IMG_WORKFLOW=/abs/path/txt2img.json
# COMFYUI_EDIT_WORKFLOW=/abs/path/edit.json
# COMFYUI_I2V_WORKFLOW=/abs/path/i2v.json

# (선택) 프롬프트 자동 다듬기용 OpenAI-호환 LLM. 미설정이면 다듬기 생략(원문 사용).
# IMAGE_PROMPT_LLM_BASE_URL=http://127.0.0.1:11434/v1
# IMAGE_PROMPT_LLM_MODEL=<model-name>

# (선택) 제한 해제 편집 모드는 이 서버 플래그가 켜진 경우에만 실효.
# IMAGE_NSFW_ENABLED=0
```

## 실행

```bash
pip install -r requirements.txt
python launcher.py        # 또는: python app.py  (APP_PORT 로 포트 지정)
```

## 테스트

```bash
python3 -m pytest        # media/ 단위 테스트(네트워크 불필요)
```

## 구조

- `app.py` — Gradio UI + 와이어링
- `media/` — 미디어 파이프라인 패키지(Gradio 비의존)
  - `backend.py` 설정 · `comfyui.py` 백엔드 클라이언트 · `llm.py` 프롬프트 다듬기 ·
    `pipeline.py` 다단계 파이프라인 · `workflows/` 워크플로 템플릿
