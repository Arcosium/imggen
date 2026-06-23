# Studio 접근 인증(로그인 + admin 승인제 가입) — 설계

- 날짜: 2026-06-23
- 브랜치: `local-comfyui-image-studio`
- 선행: 이미지·비디오 스튜디오 전면 개편(8/8 완료). 이 설계는 그 스튜디오를 인가된 인원만
  접근하도록 감싸는 인증 레이어.

## 1. 목표

image_generator(Gradio 앱, `imgvidgen.ai-ve.uk`, port 8503)를 **인가된 인원만 접근**하도록 한다.

1. **로그인 게이트** — 스튜디오와 사용설명서 모두 로그인해야 접근 가능.
2. **admin 승인제 가입** — 누구나 가입 *요청*은 할 수 있으나, admin이 승인해야 로그인 가능(pending → approved).
3. **시드 admin(최초 계정)** — 아이디 `hh09080`, 비밀번호는 소유자가 제공(평문은 어떤 커밋 파일에도
   저장하지 않고, 미리 계산한 salt+hash만 임베드). 최초 실행 시 자동 생성.
4. **로그인 시도 제한** — 아이디당 연속 5회 실패 시 일정 시간 잠금.
5. **모델명 비노출 제약 유지** — 인증 UI/문구에도 모델·엔진명 금지(기존 제약 계승).
6. **신규 외부 의존 금지** — 해싱/세션은 stdlib(`hashlib`)만. Gradio 내장 인증 활용.

## 2. 현재 상태

- `app.py`의 `__main__` 블록이 `gr.mount_gradio_app(app_api, demo, path="/", root_path=...)`로 마운트.
  커스텀 FastAPI 라우트 `/manual`, `/manual/download`, `/shutdown` 존재. 인증 없음(누구나 접근).
- Gradio **4.44.1** 설치됨(requirements는 5.x로 적혀 있으나 실행본은 4.44.1 — 기존 불일치, 본 작업 범위 밖).
  `mount_gradio_app`은 `auth`/`auth_message`/`auth_dependency` 지원.
- `.gitignore`에 `data/` 없음 → 사용자 저장소 보호를 위해 추가 필요.

## 3. Gradio 인증 메커니즘(설치본 4.44.1 확인 결과)

- `auth=(callable)`: 내장 로그인 페이지 + `/login` POST + 쿠키(`access-token[-unsecure]-{cookie_id}`) +
  `app.tokens`(token→username) 제공. `gr.Request.username`으로 로그인 사용자 식별. 콜백 시그니처는
  `(username, password) -> bool` — **요청/IP는 받지 못함**(레이트리밋은 아이디 단위로).
- `auth_dependency=(callable)`: 직접 통제 가능하나 로그인 UI 없음, 미인증 시 401만 반환.

**채택**: 내장 `auth=`. 깔끔한 로그인 페이지·세션을 공짜로 얻는다. 단점(세션이 Gradio 내부라
별도 FastAPI 라우트를 같은 세션으로 게이트하기 어려움)은 **사용설명서를 게이트된 Gradio 탭으로
이동**해 회피한다(아래 §7).

## 4. 모듈 구조

```
image_generator/
  auth/
    __init__.py
    store.py          # 사용자 저장소(JSON) + pbkdf2 해싱 + 시드 admin + 레이트리밋
  app.py              # authenticate 콜백 + mount auth= + /signup 공개 라우트 + 관리자/설명서 탭
  data/users.json     # 런타임 생성(gitignore: data/)
  tests/test_auth_store.py
  tests/test_auth_app.py
```

## 5. 사용자 저장소 (`auth/store.py`)

- 저장: `data/users.json`. 레코드:
  `{username: {"salt": hex, "hash": hex, "role": "admin"|"user", "status": "pending"|"approved"|"rejected", "created": epoch}}`
- 해싱: `hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITER)` — `ITER=200_000`.
  검증은 `hmac.compare_digest`로 상수시간 비교.
- **시드 admin**: 모듈에 `BOOTSTRAP_ADMIN = {"username":"hh09080","salt":<hex>,"hash":<hex>,"role":"admin","status":"approved"}`
  를 임베드(평문 아님; 컨트롤러가 사전 계산). `seed_admin()`은 `data/users.json`이 없거나 admin이 없으면
  이 레코드로 생성. env `ADMIN_PASSWORD`가 있으면 그 값으로 해시를 재계산해 시드(운영자 교체 경로).
- 공개 API:
  - `verify_credentials(username, password) -> bool` — 사용자 존재 ∧ status==approved ∧ 해시 일치.
  - `create_pending(username, password) -> (ok: bool, msg: str)` — 빈값/중복 거부, 아니면 pending 생성.
  - `list_pending() -> list[str]`
  - `approve(username) -> bool` / `reject(username) -> bool`
  - `is_admin(username) -> bool`
- 동시성: 모듈 `threading.Lock`으로 load/save 보호, 임시파일 + `os.replace`로 원자적 쓰기.

### 5b. 로그인 시도 제한 (레이트리밋)
- 인메모리 `_attempts: dict[str, {"count": int, "locked_until": epoch}]` + 락(영속화 불필요).
- 파라미터: `LOGIN_MAX_ATTEMPTS`(기본 5), `LOGIN_LOCKOUT_SECONDS`(기본 900=15분) — env 오버라이드.
- `check_login(username, password) -> bool`(로그인 게이트가 호출):
  1. 현재 `locked_until > now`면 즉시 False(잠금 중).
  2. `verify_credentials` 성공이면 해당 아이디 카운터 리셋 후 True.
  3. 실패면 count+1. count >= MAX면 `locked_until = now + LOCKOUT`, count 리셋. False 반환.
- `authenticate`(Gradio 콜백)는 `check_login`을 호출. (Gradio 로그인 실패 메시지는 일반화되어
  "잠금" 여부를 별도 표기하지 않음 — 잠금 자체는 동작.)

## 6. 로그인 (Gradio 내장 `auth=`)

- `__main__`의 마운트를 `gr.mount_gradio_app(app_api, demo, path="/", root_path=root_path,
  auth=authenticate, auth_message=AUTH_MESSAGE)`로 변경.
- `authenticate = lambda u, p: store.check_login(u, p)`(또는 동등 함수).
- `AUTH_MESSAGE`: 모델명 없는 안내 + 가입 링크. 예: `'승인된 계정만 입장할 수 있습니다. 계정이 없다면 <a href="/signup">가입 신청</a>'`.

## 7. 가입(공개) · 관리자/설명서(게이트)

### 7.1 가입 — 공개 FastAPI 라우트
- `GET /signup` → 아이디·비밀번호 입력 HTML 폼(다크 테마, 모델명 없음).
- `POST /signup`(form) → `store.create_pending` → 성공("가입 신청 완료. 관리자 승인 후 로그인 가능")
  또는 실패("이미 존재하는 아이디입니다" 등) HTML. Gradio 게이트 밖이라 누구나 접근.

### 7.2 관리자 승인 — 게이트된 Gradio 탭
- build_ui에 **🔐 관리자 탭** 추가. 모든 핸들러는 `request: gr.Request`를 받아 `store.is_admin(request.username)`
  서버측 검증.
- 구성: 대기 목록(`gr.Dropdown`/`gr.Dataframe`) + `🔄 새로고침` + 선택 아이디 `승인`/`거절` 버튼.
- 비관리자가 이 탭의 액션을 호출하면 "관리자만 사용할 수 있습니다." 반환, 데이터/변경 없음.

### 7.3 사용설명서 — 게이트된 Gradio 탭으로 이동
- 기존 `__main__` 내 `_render_manual_html()`/`MANUAL_DOCX`를 **모듈 레벨**로 올려 build_ui에서 사용.
- **📖 사용설명서 탭**: `gr.HTML(render_manual_html())` + `.docx` 다운로드 버튼(`gr.DownloadButton`).
- 공개 `/manual`·`/manual/download` FastAPI 라우트 및 헤더의 외부 링크 버튼 제거(설명서가 게이트됨).
- `/shutdown` 비콘은 기존대로 유지(데스크톱 종료용; 본 작업 범위 밖).

## 8. 보안/에러

- 비밀번호 평문 저장·커밋 금지(해시만). `data/`(users.json 포함) gitignore.
- 메시지 일반화: 로그인 실패는 Gradio 기본(일반), 가입 실패는 "이미 존재하는 아이디입니다"/"입력값을 확인하세요".
- 시드 admin 비밀번호 평문은 어떤 커밋 파일(코드/스펙/플랜)에도 기록하지 않는다 — salt+hash만.

## 9. 테스트 (TDD)

- `tests/test_auth_store.py`(gradio 비의존, tmp `data/users.json` monkeypatch):
  - seed_admin 멱등(두 번 호출해도 admin 1개), admin status=approved/role=admin.
  - verify_credentials: 승인+정답 True; 오답 False; pending/rejected 사용자 False; 없는 사용자 False.
  - create_pending: 신규 ok·pending; 중복 거부; 빈값 거부.
  - approve/reject: pending→approved/rejected 전이; verify는 approved만 통과.
  - is_admin.
  - 해시 라운드트립(같은 평문+salt → 같은 hash; 다른 평문 → 다름).
  - 레이트리밋: 5회 실패 후 잠금(정답이어도 False); 성공 시 카운터 리셋; 잠금 시간 경과 후 해제(시간 monkeypatch).
- `tests/test_auth_app.py`(app import; gradio 설치됨):
  - `authenticate` 콜백이 store.check_login에 연결됨(승인 사용자 True, 미승인 False).
  - signup POST 핸들러 로직: 신규→pending 생성, 중복→실패 메시지(핸들러 함수 직접 호출 또는 store 경유).
  - 관리자 탭 핸들러: 가짜 `request`(.username=admin)면 대기목록/승인 동작; 비관리자면 "관리자만" 반환·무변경.
  - build_ui 여전히 생성되고 모델명 누출 없음(기존 테스트 유지).

## 10. 영향 파일 요약

- 신규: `auth/__init__.py`, `auth/store.py`, `tests/test_auth_store.py`, `tests/test_auth_app.py`
- 수정: `app.py`(authenticate/마운트 auth=, /signup 라우트, 관리자·설명서 탭, manual 모듈화, 헤더 버튼 제거),
  `.gitignore`(data/ 추가), `README.md`(인증/가입/admin 안내 섹션 추가)
- 런타임 생성(비커밋): `data/users.json`

## 11. 범위 밖 (YAGNI)

- 비밀번호 재설정/이메일 인증, 역할 세분화, IP 기반 차단, 세션 만료 커스터마이즈(Gradio 기본 사용),
  /shutdown 게이팅.
