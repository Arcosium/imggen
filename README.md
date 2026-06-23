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

## 접근 및 계정

스튜디오와 사용설명서는 **승인된 계정만** 접근할 수 있습니다.

- **로그인**: 첫 화면에서 아이디·비밀번호로 로그인합니다. 연속 5회 실패하면 일정 시간 잠깁니다.
- **가입**: 로그인 화면의 "가입 신청" 링크(`/signup`)에서 아이디·비밀번호로 신청합니다.
  신청은 **관리자 승인 후** 로그인할 수 있습니다.
- **관리자 승인**: 관리자 계정으로 로그인하면 "🔐 관리자" 탭에서 대기 중 신청을 승인/거절합니다.
- **최초 관리자**: 아이디 `hh09080`. 최초 실행 시 자동 생성됩니다. 비밀번호는 소유자가 보관하며,
  환경변수 `ADMIN_PASSWORD`로 교체할 수 있습니다.

```env
# (선택) 최초 관리자 비밀번호 교체 — 최초 실행(계정 생성) 전에 설정
# ADMIN_PASSWORD=...
# (선택) 로그인 시도 제한
# LOGIN_MAX_ATTEMPTS=5
# LOGIN_LOCKOUT_SECONDS=900
```

> 계정 정보는 `data/users.json`에 비밀번호 **해시**로만 저장되며 git에 커밋되지 않습니다.

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
