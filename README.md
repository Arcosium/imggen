# Image Studio — 로컬 이미지 생성 스튜디오

로컬 미디어 백엔드(ComfyUI)를 통해 이미지를 생성하는 Gradio 데스크톱/서비스 앱.
사용자는 모델을 고르지 않으며, API 키 입력도 없습니다.

## 기능

### 🎨 이미지 생성
- **텍스트 → 이미지**: 프롬프트만 입력
- **프롬프트 자동 다듬기**(기본 ON): 짧은 아이디어를 고화질 프롬프트로 확장. LLM 백엔드가 없으면 입력 그대로 사용(자동 폴백)
- **비율**: 1:1 / 9:16 / 16:9 / 3:4 / 4:3
- **장수**: 1 / 2 / 4장. 한 장에 약 8분(진행 상태에 경과 시간 표시). 시드는 매번 무작위

### 🖌️ 이미지 편집
- **대상만**: 프롬프트대로 편집
- **레퍼런스 + 대상**: 레퍼런스의 분위기 이식 또는 장면 합성

> 영상(i2v) 기능은 2026-07-09 전면 제거되었습니다(모델·워크플로·UI 모두).

## 접근 및 계정

스튜디오와 사용설명서는 **승인된 계정만** 접근할 수 있습니다.

- **로그인**: 첫 화면에서 아이디·비밀번호로 로그인합니다. 연속 5회 실패하면 일정 시간 잠깁니다.
- **가입**: 로그인 화면의 "가입 신청" 링크(`/signup`)에서 아이디·비밀번호로 신청합니다.
  신청은 **관리자 승인 후** 로그인할 수 있습니다.
- **관리자 승인**: 관리자 계정으로 로그인하면 "관리자" 탭에서 대기 중 신청을 승인/거절합니다.
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

# (선택) 프롬프트 자동 다듬기용 OpenAI-호환 LLM. 미설정이면 다듬기 생략(원문 사용).
# IMAGE_PROMPT_LLM_BASE_URL=http://127.0.0.1:11434/v1
# IMAGE_PROMPT_LLM_MODEL=<model-name>

# 제한 해제 모드(고급 설정·편집 탭의 토글)는 이 서버 플래그가 켜진 경우에만 보이고 실효.
# 2026-09-17 부터 운영 유닛에서 1 — 가입이 관리자 승인제라 로그인한 전체 계정에 연다.
# 미성년을 가리키는 표현은 이 모드에서 항상 거절한다(끄는 설정 없음).
# IMAGE_NSFW_ENABLED=1
```

## 실행

```bash
pip install -r requirements.txt
python launcher.py        # 또는: python app.py  (APP_PORT 로 포트 지정)
```

## 안드로이드 앱

`mobile/` 은 imggen.ai-ve.uk 를 여는 WebView 셸(uk.aive.imggen)이다. 웹을 고치면 앱은 재빌드할 필요 없다.
셸이 더하는 것: 사진 업로드(파일 선택기), 결과 저장(쿠키 실은 DownloadManager + 갤러리 blob 저장 훅), 화면 꺼짐 방지.

```bash
IMGGEN_DRIVE_UPLOAD=1 mobile/build_apk.sh   # → mobile/ImageStudio.apk, gdrive:apk/ImageStudio.apk
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
