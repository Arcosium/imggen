# Image & Video Laboratory — Gemini · Imagen · Veo 통합 크리에이티브 스튜디오

> Google 의 Gemini Image / Imagen 4 / Veo 3.1 모델을 한 Gradio 인터페이스에서 채팅처럼 다루는 로컬 데스크톱 앱.

이미지 생성·편집·재생성 + 비디오 렌더링까지를 하나의 채팅 UI 에서 처리합니다.
프롬프트뿐 아니라 Word / Excel / PDF / TXT 문서를 드래그 앤 드롭하면 자동으로 텍스트를 추출해
프롬프트의 컨텍스트로 사용하며, 모든 세션은 타임스탬프 폴더에 자동 저장돼 나중에 다시 불러올 수 있습니다.

- **이미지**: Gemini 3.1 Flash Image / 3 Pro Image / 2.5 Flash Image / Imagen 4 (Standard·Ultra·Fast)
- **비디오**: Veo 3.1 Standard·Fast·Lite / Veo 3.0 / Veo 2.5 (720p / 1080p / 4K)
- **UI**: Gradio 5 (다크 테마, 한국어)
- **배포**: Python 직접 실행 또는 PyInstaller `.exe`

---

## 주요 기능

### 🎨 이미지 스튜디오
- **텍스트 → 이미지** (Gemini 3 Pro / Flash / Imagen 4)
- **이미지 편집** (참조 이미지 업로드 + 채팅으로 수정 지시)
- **배치 생성** 1 ~ 10장 연속
- **종횡비** 14종 (1:1, 1:4, 3:2, 16:9, 9:16, 4:5, 21:9, …)
- **해상도** 512px / 1K / 2K / 4K
- **Extended Thinking** ("Minimal" / "High", Gemini 3 모델 한정)
- **문서 → 프롬프트**: Word / Excel / PDF / TXT 드롭하면 자동 추출 후 컨텍스트 주입
- **세션 히스토리**: AI 가 자동으로 세션 이름 생성 ("파란머리_사이버펑크"), 폴더 단위로 보존

### 🎬 비디오 렌더링 룸
- **텍스트 → 비디오** (Veo 3.1 / 3.0 / 2.5)
- **First / Last frame pinning**: 시작/끝 프레임을 특정 이미지로 고정
- **참조 이미지** 최대 3장 (캐릭터/소품 일관성)
- **문서 → 비디오**: Doc/Excel 텍스트를 자동으로 씬 묘사로 변환
- **비디오 확장**: 마지막 비디오 끝에 +7초씩 자동 이어 붙여 최대 64초까지
- **종횡비**: 16:9 (YouTube), 9:16 (Shorts)

## 빠른 시작

### 1. 의존성

```bash
pip install -r requirements.txt
# gradio>=5.0.0,<6.0.0
# google-genai>=1.0.0
# pillow>=10.0.0
# fastapi>=0.110.0
# uvicorn>=0.27.0
# python-docx>=1.1.0
# pandas>=2.0.0
# openpyxl>=3.1.0
```

### 2. Gemini API 키

Google AI Studio (https://aistudio.google.com) 에서 발급받은 키를 준비하세요.
앱 안 사이드바 입력칸에 붙여넣으면 자동으로 `.env` 에 저장됩니다.

```bash
# .env (앱이 자동 생성)
GEMINI_API_KEY=AIza...
```

### 3. 실행

#### Python 직접 실행
```bash
python launcher.py
# Gradio 가 localhost:7860 에 기동 → 브라우저 자동 오픈
```

#### Windows 데스크톱 앱
PyInstaller 로 빌드된 `.exe` 를 더블클릭하면 끝.
`launcher.py` 가 PyInstaller 환경에서 발생하는 `gradio_client` 스키마 파싱 버그를
자동 패치한 뒤 앱을 부팅합니다.

## 디렉터리 구조

```
image_generator/
├── app.py              # 49KB — Gradio UI + Gemini/Imagen/Veo 호출 전체
├── launcher.py         # 2.6KB — PyInstaller wrapper (gradio_client 패치 + BASE_DIR 보정)
├── requirements.txt    # 의존성
├── 사용설명서.docx      # 한국어 사용 설명서 (앱 내 /manual 로 노출)
├── server_ready.flag   # 기동 완료 신호 (HTTP 가 받기 시작하면 생성)
├── .env                # GEMINI_API_KEY (자동 생성)
├── history/            # 세션 JSON + 메타데이터 (자동 생성)
└── outputs/            # 생성된 PNG (자동 생성)
```

## 모델 라인업

```python
# app.py
IMAGE_MODEL_MAPPING = {
  "Gemini 3.1 Flash Image (1K: ~$0.067/장)": "gemini-3.1-flash-image-preview",
  "Gemini 3 Pro Image (1K/2K: ~$0.134/장)":  "gemini-3-pro-image-preview",
  "Gemini 2.5 Flash Image (1K: ~$0.039/장)": "gemini-2.5-flash-image",
  "Imagen 4 Standard / Ultra / Fast":        "imagen-4.0-*-generate-001",
}

VIDEO_MODEL_MAPPING = {
  "Veo 3.1 Standard / Fast / Lite": "veo-3.1-*-generate-preview",
  "Veo 3.0 Standard / Fast":        "veo-3.0-*-generate-001",
}
```

비용은 모델 라벨에 한국어로 함께 표기돼 있어 사용자가 즉시 비교 가능.

## 사용 흐름

1. **사이드바에 Gemini API 키 입력** → 자동 저장
2. **모델 / 해상도 / 종횡비 / Thinking 레벨 선택**
3. **이미지 탭**: 채팅창에 프롬프트 입력 (또는 참조 이미지 업로드)
4. **🚀 로켓 전송** 클릭 → 진행 메시지 ("✨ Gemini가 상상력을 동원하는 중…") 후 결과 표시
5. **결과 카드 클릭** → 모달에서 채팅으로 수정 지시 ("배경을 우주로 바꿔줘")
6. **세션 자동 저장**: AI 가 세션 이름 생성, `history/<timestamp>_<title>/` 에 저장
7. **세션 다시 열기**: 좌측 패널의 과거 프로젝트 클릭

비디오 탭도 동일한 흐름이지만 결과는 mp4, 진행 메시지는 "⏳ Veo 동영상 렌더링 서버 접속 중…"

## 문서 업로드 동작

| 형식 | 처리 |
|---|---|
| `.docx` | python-docx 로 본문 텍스트 추출 |
| `.xlsx`, `.xls` | openpyxl + pandas 로 시트별 텍스트화 |
| `.csv` | pandas read_csv |
| `.txt` | UTF-8 디코드 |
| `.pdf` | (직접 추출 — 단순 텍스트만) |

추출된 텍스트는 프롬프트의 시스템 컨텍스트로 주입됩니다 (Gemini 에 직접 첨부 X — 토큰 절약).

## 핵심 함수 (app.py)

| 함수 | 역할 |
|---|---|
| `get_client(api_key)` | `genai.Client()` 캐시 (키별 1 인스턴스) |
| `_run_imagen()` | Imagen 배치 생성 |
| `_generate_video_core()` | Veo 스트리밍 (progress yield) |
| `get_image_config()` | `GenerateContentConfig` (thinking / search / safety) 빌드 |
| `process_image_interaction()` | 메인 채팅 루프 (업로드 → 생성 → 히스토리) |
| `generate_modal_image()` | 모달 안에서 이미지 편집/재생성 |
| `_extract_text_from_doc()` | 문서 → 텍스트 (로컬, API 비용 X) |
| `_build_final_prompt()` | 채팅 히스토리 + 해상도 힌트 합성 |
| `_generate_session_title()` | AI 가 세션 이름 자동 생성 |
| `_list_projects()` / `_load_project()` | history/ 탐색 / 복원 |

## 운영 노트

- **시간대**: 파일명 `20260515_140230_…` 형식 (Asia/Seoul, ZoneInfo)
- **포트**: Gradio 기본 `7860` (변경 시 `app.py` 의 `launch(server_port=)` 수정)
- **종료**: `/shutdown` BeaconAPI 엔드포인트로 graceful close — `.exe` 종료 시 트리거
- **키 저장**: API 키는 `.env` 에 평문 저장. `.gitignore` 에 포함됨
- **비용 주의**: Veo / Imagen 4 Ultra 는 단가가 높음. 모델 라벨에 표기된 가격 확인 후 사용 권장

---

## English Summary

Local desktop creative studio that wraps Google's Gemini Image, Imagen 4, and
Veo 3.1 APIs in a single chat-style Gradio interface. Supports text-to-image,
image editing with reference uploads, batch generation, document-to-prompt
context (Word/Excel/PDF/TXT), text-to-video, first/last-frame pinning, and
auto-extension up to 64 seconds. All sessions auto-save to a timestamped
project folder for later reload. Distributable as a Windows .exe via
PyInstaller.

**Stack:** Gradio · google-genai SDK · FastAPI/Uvicorn · PIL · python-docx · pandas/openpyxl

## License

API costs are billed by Google directly to your API key. Be mindful when
running large batches or video generation.
