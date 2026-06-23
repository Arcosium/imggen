# Image & Video Studio 전면 개편 — 설계

- 날짜: 2026-06-23
- 브랜치: `local-comfyui-image-studio`
- 참고 소스: `/home/opc/projects/ArcAI.ve` 의 로컬 ComfyUI 미디어 파이프라인
  (`clients/comfyui_client.py`, `clients/local_backend.py`, `clients/image_pipeline.py`,
  `clients/media_jobs.py`, `clients/comfyui_workflows/*.json`)

## 1. 목표

image_generator(Gradio 앱, port 8503, `imgvidgen.ai-ve.uk`)의 이미지·비디오 스튜디오를
ArcAI.ve의 생성 로직을 참고해 전면 개편한다.

핵심 요구사항:

1. **모델명 비노출** — 사용자에게 어떤 모델/엔진을 쓰는지 일절 표기하지 않는다.
   UI·사용자 노출 텍스트에 FLUX / Qwen / Veo / Gemini / Imagen / ComfyUI 등 금지.
   기능 중심 중립 표현만 사용("이미지 생성", "고화질 편집", "영상화").
2. **이미지 파이프라인 고도화** — ArcAI.ve의 `expand(LLM) → txt2img → edit` 다단계 도입.
3. **비디오 부활** — 로컬 image→video(i2v) 기반. 텍스트→영상(t2v)과 이미지→영상(i2v) **둘 다** 제공.
4. **프롬프트 확장 기본 ON** — 짧은 아이디어를 LLM이 고화질 프롬프트로 확장. 단, LLM 백엔드가
   없거나 실패하면 **원문 프롬프트로 안전 폴백**(앱이 죽지 않음).
5. **죽은 코드 제거 + README 갱신** — app.py의 Gemini/Imagen/Veo 잔재 전부 삭제, README를
   ComfyUI 단일 경로로 갱신.

## 2. 현재 상태 (개편 대상)

- `app.py` (1145줄): Gradio 채팅형 UI. 이미지 탭은 `local_image_pipeline.generate/edit` 호출로
  마이그레이션됐으나 평탄함. 다음 죽은 코드가 잔존:
  - `process_image_interaction` 의 `return`(313줄) 이후 Gemini 이미지 생성 코드(315–450)
  - `generate_modal_image` 의 `return`(477줄) 이후 Gemini 모달 재생성 코드(479–534)
  - Veo 비디오 스튜디오 전체(554–1014, 탭 `visible=False`)
  - 모델명 누출: 사이드바 "FLUX 생성 → Qwen Image Edit", 탭 제목 "(ComfyUI)",
    `VIDEO_MODEL_MAPPING`/`IMAGE_MODEL_MAPPING`(Veo/Gemini/Imagen)
- `local_image_pipeline.py` (67줄): ArcAI.ve를 평탄화한 `generate`/`edit`만. 프롬프트 확장·비디오·
  단계별 메모리 언로드·모듈 분리 없음.
- 워크플로 JSON 없음, `.env` 없음. ComfyUI는 "앱이 도는 머신"에서 `COMFYUI_BASE_URL`로 가리키는 전제
  (데스크톱 .exe = 사용자 PC, 서비스 = GPU 호스트).

## 3. 채택 접근법 (B)

파이프라인은 모듈로 깔끔히 이식하되, ArcAI.ve의 `media_jobs.py`(잡 스토어 + 폴링)는 **이식하지 않는다**.

근거: `media_jobs.py`는 Flask가 JSON을 주고 별도 JS 프론트가 폴링하기 때문에 존재한다.
image_generator는 Gradio라 **서버 측 제너레이터 `yield`로 진행상황을 UI에 직접 푸시**할 수 있다.
파이프라인은 `on_stage(stage)` 콜백 훅을 유지(UI-비의존·테스트 가능)하고, Gradio 핸들러가 그 콜백을
`yield`/`gr.Progress` 업데이트로 연결한다. 잡-스토어/폴링 레이어 전체를 생략 → 부품 최소, 관용적.

(대안 A=충실 이식은 불필요한 레이어 잔존, C=단일 파일 확장은 모듈 분리 이점 상실로 기각.)

## 4. 모듈 구조

`local_image_pipeline.py`(평탄)를 삭제하고 `media/` 패키지로 교체한다.

```
image_generator/
  app.py                 # Gradio UI + 와이어링만 (대폭 슬림화)
  media/
    __init__.py
    backend.py           # 설정 단일소스 (ArcAI.ve local_backend.py 적응)
    comfyui.py           # 얇은 ComfyUI HTTP 클라이언트 (ArcAI.ve comfyui_client.py 적응)
    llm.py               # 프롬프트 확장용 OpenAI-호환 LLM 호출 (실패 시 폴백) — 신규
    pipeline.py          # 다단계 파이프라인 (ArcAI.ve image_pipeline.py 적응)
    workflows/
      txt2img.json       # ArcAI.ve flux_txt2img.json 복사 (중립 파일명)
      edit.json          # ArcAI.ve qwen_image_edit.json 복사
      i2v.json           # ArcAI.ve wan_i2v.json 복사
  local_image_pipeline.py  # 삭제
```

ArcAI.ve 대비 변경점:
- `routes` 의존(순환방지 lazy import) → 독립 `llm.py`.
- `media_jobs.py` 생략(Gradio 제너레이터로 대체).
- 워크플로 파일명을 모델명 없는 중립 이름으로.
- 이미지/비디오 백엔드는 ComfyUI 전용(ArcAI.ve의 openrouter 폴백 경로 미이식). LLM(확장)만 선택적.

### 4.1 `media/backend.py`
설정 단일 소스. `routes` import 안 함.
- `ASPECTS` = `{"1:1":(1024,1024), "9:16":(576,1024), "16:9":(1024,576), "3:4":(768,1024), "4:3":(1024,768)}`
- `aspect_dims(name)` — 미지 이름은 1:1 폴백.
- `image_config()` / `video_config()` — `COMFYUI_BASE_URL`, 워크플로 경로(기본 `media/workflows/*.json`),
  체크포인트/LoRA/frames/fps/steps/cfg 등. env로 오버라이드 가능.
- `llm_config()` — 프롬프트 확장용. 기본 로컬 OpenAI-호환(`http://127.0.0.1:11434/v1` 등) env 기반.
- `nsfw_enabled(requested)` / `resolve_image_mode(requested)` — `IMAGE_NSFW_ENABLED` 서버 플래그가
  켜진 경우에만 NSFW 허용, 아니면 SFW로 강등.

### 4.2 `media/comfyui.py`
ArcAI.ve `comfyui_client.py`의 API 형태를 이식하되, **stdlib `urllib`로 구현**한다
(현재 `local_image_pipeline.py`와 동일 방식 — PyInstaller `.exe` 배포에서 `requests` 추가 의존을
피한다. multipart 업로드도 현재 코드처럼 직접 조립):
`load_template`, `fill_template`(단독 토큰은 원래 형 보존), `queue_prompt`, `poll_history`,
`first_image_ref`, `first_media_ref`(gifs/videos/images), `free_memory`(베스트에포트),
`fetch_image`, `upload_image`.

### 4.3 `media/llm.py` (신규)
OpenAI-호환 `/chat/completions` 호출 1개 함수 + `expand_prompt(idea, *, aspect, style)`.
- 백엔드 미설정/연결 실패/타임아웃 → **예외 던지지 않고 원문(idea) 반환**(폴백).
- 시스템 프롬프트: 아이디어를 vivid·detailed 영문 이미지 프롬프트로 확장(ArcAI.ve `_EXPAND_SYSTEM` 참고).

### 4.4 `media/pipeline.py`
ArcAI.ve `image_pipeline.py` 적응:
- `txt2img(prompt, *, aspect, seed, steps, cfg)` → bytes
- `edit_image(image_bytes, instructions, *, mode, ...)` → bytes (mode=sfw면 NSFW LoRA weight=0)
- `img2video(image_bytes, prompt, *, aspect, negative, seed)` → (bytes, mime); 폴링 타임아웃 넉넉히(900s)
- `make_image(*, idea, prompt, aspect, mode, edit_instructions, expand, on_stage)` → {image, prompt_used}
  - expand(기본 True, 폴백 가능) → txt2img → (edit_instructions 있거나 mode=uncensored면) edit
- `make_video(*, idea, prompt, aspect, mode, edit_instructions, input_image, expand, on_stage)`
  → {video, mime, base_image, edited_image, prompt_used}
  - **i2v 직행**: `input_image` 가 주어지면 expand/txt2img/edit 생략하고 바로 img2video
  - **t2v**: input_image 없으면 expand → txt2img → (조건부 edit) → img2video
  - 단계 사이 `comfyui.free_memory()`로 모델 언로드(피크 1모델)
- `on_stage(stage)` 콜백으로 단계 진행 신호(queued/expand/txt2img/edit/img2video/free/done).

### 4.5 `media/workflows/*.json`
ArcAI.ve `comfyui_workflows/`의 3종을 중립 파일명으로 복사. `%TOKEN%` 플레이스홀더 유지.
체크포인트/LoRA 파일명은 워크플로 내부에 남지만(ComfyUI 필수, 운영자 대상) **사용자 UI엔 안 보임**.

## 5. Gradio UI

탭 2개, 좌 컨트롤 / 우 결과 스튜디오 레이아웃. 모든 노출 텍스트는 중립.

### 5.1 🎨 이미지 스튜디오
- 좌: 프롬프트(아이디어), 참조 이미지 업로드(편집 시), 비율 dropdown,
  `▸ 고급` accordion(편집 지시, 프롬프트 확장 토글[기본 ON], NSFW 토글[서버 허용 시만 실효]),
  [✨ 생성] / [⏹ 중지]
- 우: 결과 이미지, 단계 진행 표시(상태 텍스트 + `gr.Progress`), ⬇️ 다운로드, 🕘 최근 결과 갤러리
- 핸들러는 제너레이터: `make_image(on_stage=yield콜백)` 진행을 실시간 스트리밍.

### 5.2 🎬 비디오 스튜디오
- 모드 라디오: `텍스트→영상` / `이미지→영상`
- 공통: 프롬프트, 비율 dropdown, [🎬 생성] / [⏹ 중지]
- `이미지→영상` 모드: 입력 이미지 업로드 노출(필수)
- 우: 영상 플레이어 + 진행 표시
- `make_video` 제너레이터로 진행 스트리밍.

### 5.3 보존/변경
- 문서 드롭(Word/Excel/PDF/TXT)→텍스트 추출 컨텍스트: 이미지 탭에 **선택적으로 유지**(중립 처리).
- 세션 히스토리(채팅 JSON 프로젝트): 채팅 UI 제거에 따라 **간소화** — 출력물은 `outputs/`에
  타임스탬프로 저장, 탭별 "최근 결과" 갤러리로 대체. 복잡한 chat-tuples 프로젝트 저장/로드는 제거.
- API 키 입력칸 제거(이미지/비디오 모두 로컬 백엔드).
- 사용설명서(`/manual`) 라우트와 `/shutdown` 비콘은 유지.

## 6. 보안/안전

- NSFW: 서버 env `IMAGE_NSFW_ENABLED` 가 켜진 경우만 실효(`resolve_image_mode`), 아니면 SFW 강등.
- 에러 메시지: ComfyUI/소켓 등 내부 메시지를 사용자에게 노출하지 않고 일반화
  ("이미지 백엔드에 연결할 수 없습니다") + 서버 로그만.
- 백엔드 부재 시 앱은 정상 기동하고, 생성 시도 시에만 친절한 에러.

## 7. 테스트 (TDD)

ComfyUI HTTP/LLM HTTP를 목킹한 유닛 테스트:
- `comfyui.py`: `fill_template`(단독 토큰 형 보존 + 임베드 치환), `first_image_ref`/`first_media_ref`.
- `llm.py`: `expand_prompt` 정상 확장 + 백엔드 실패 시 원문 폴백.
- `pipeline.py`: `make_image` 단계 순서·edit 발동 규칙(sfw+지시없음→1단계, uncensored/지시→edit),
  `make_video` t2v vs i2v 분기, NSFW weight 게이팅.
- UI는 수동 검증(가능하면 webapp-testing).

## 8. 범위 밖 (YAGNI)

- 외부 REST 잡 API(`media_jobs` 폴링) — Gradio 내부 사용엔 불필요.
- openrouter/Gemini 이미지·비디오 폴백 — 로컬 ComfyUI 단일 경로로 확정.
- 배치 N장 연속 생성(기존 슬라이더) — 단순화 위해 1장 기본(추후 필요 시 재도입).
- 비디오 auto-extend(+7초 이어붙이기) — Veo 전용 기능, i2v엔 미적용.

## 9. 영향 파일 요약

- 신규: `media/__init__.py`, `media/backend.py`, `media/comfyui.py`, `media/llm.py`,
  `media/pipeline.py`, `media/workflows/{txt2img,edit,i2v}.json`, `tests/test_*.py`
- 수정: `app.py`(슬림화·UI 재작성), `README.md`(갱신), `requirements.txt`(google-genai 제거 — 신규 의존 없음, stdlib urllib 사용)
- 삭제: `local_image_pipeline.py`
