# GilJob v2

GilJob v2는 **한 대의 서버에서 Docker Compose로 실행하는 self-hosted AI 면접 시스템 scaffold**입니다. 목표는 기존 `/home/hoddukzoa/GilJob`를 건드리지 않고, 별도 `GilJob_v2` 작업 공간에서 LiveKit 기반 면접룸, GilJobE STT/분석, Gemini 질문/TTS, SpatialReal RTC 아바타를 단계적으로 붙이는 것입니다. 현재 `main`은 scaffold/contract-test 단계이며, production-ready 또는 전체 compose-build green 상태로 간주하지 않습니다.

![GilJob v2 아키텍처](docs/assets/architecture.svg)

> 중요: 이 repository/worktree는 기존 `/home/hoddukzoa/GilJob`와 분리된 v2 작업 공간입니다. 기존 GilJob 폴더를 복사·삭제·수정하지 않습니다.
>
> Release-readiness note: 2026-06-11 main-branch audit 기준, `analysis-engine` Docker build failure, public `/analysis/*` exposure, unauthenticated session/provider broker routes, and stale verification docs are known gaps. See [`docs/reviews/main-branch-readiness-20260611.md`](docs/reviews/main-branch-readiness-20260611.md).

## 현재 구현 상태

구현됨:

- 단일 서버 Docker Compose 기반 scaffold
- Caddy ingress (`/api/*` broker, direct `/ai/*`, `/tts/*`, `/avatar/*` 차단; 현재 `/analysis/*`는 development boundary로 public proxy됨)
- Python 기반 `api`, `web`, `ai-engine`, `agent1` scaffold
- `services/analysis-engine` GilJobE dependency/health/subscriber boundary (현재 Docker build blocker 있음)
- Postgres service 및 token-hash schema contract (runtime API persistence는 아직 in-memory)
- optional self-hosted LiveKit/coturn media overlay
- `POST /api/sessions` 후보자 session 생성
- LiveKit candidate join token 발급
- SpatialReal AvatarKit RTC용 별도 subscribe-only avatar viewer token 발급
- production 형태의 interview routes
  - `/interviews/new`
  - `/interviews/:id/lobby`
  - `/interviews/:id/room`
  - `/interviews/:id/report`
- 실제 room route에서 LiveKit 자동 join
- room 내부 prejoin/setup UI 제거
- Zoom/Google Meet형 light interview room shell
- push-to-talk 답변 흐름
  - 면접관 질문/TTS 종료 후 `답변 시작` 활성화
  - 후보자가 버튼을 눌러 답변 시작
  - 다시 버튼을 눌러 답변 종료 및 다음 질문 요청
- Gemini next-question provider
- Gemini native TTS provider (`gemini-3.1-flash-tts-preview`)
- SpatialReal session-token broker
- SpatialReal RTC/LiveKit client renderer shell
- SpatialReal Python SDK LiveKit egress 시도 경로
- 로컬 Whisper/STT service 제거 완료; STT는 `GilJobE` 기반 `services/analysis-engine` 경계
- token redaction 및 raw token 비노출 contract test

아직 범위 밖 또는 제한적:

- CV/job parsing
- production-grade Main LLM orchestration/state machine
- final report generator
- production domain/TLS/hardening
- Redis/event bus 전환
- `analysis-engine` Docker image build green 상태 (`praat-parselmouth` native build toolchain issue가 남아 있음)
- `/analysis/*` production auth boundary; 현재는 browser가 development proxy를 직접 호출합니다.
- session/provider broker auth hardening; 현재 `/api/sessions`와 question/TTS/avatar broker는 production user-auth gate가 없습니다.
- Postgres runtime persistence; 현재 schema/service만 있고 API token hash store는 process memory입니다.
- SpatialReal 아바타 영상의 end-to-end 검증은 LiveKit이 SpatialReal cloud에서 접근 가능한 public `wss://...`와 WebRTC media/TURN 구성이 필요합니다. Cloudflare Tunnel은 signaling/WebSocket에는 유용하지만, WebRTC media 경로는 추가 검증이 필요합니다.

## Production UX 기준

라우트 책임은 아래처럼 나눕니다.

| Route | 책임 | 현재 상태 |
|---|---|---|
| `/interviews/new` | CV, 직무 링크, persona 선택 진입점 | placeholder |
| `/interviews/:id/lobby` | device readiness, 입장 전 확인 | placeholder |
| `/interviews/:id/room` | 실제 면접룸 | LiveKit 자동 join + push-to-talk room shell |
| `/interviews/:id/report` | 면접 종료 후 report | placeholder |

`room`은 Zoom/Google Meet처럼 “이미 방에 들어온 화면”이어야 합니다. 따라서 room 내부에는 prejoin form, endpoint 입력, “Join room” 버튼, 개발용 긴 설명문을 두지 않습니다. 입장 준비는 lobby가 담당하고, room은 mic/camera/leave/report control과 숨김 drawer형 면접 상태 패널만 보여줍니다.

## 아키텍처 요약

핵심 경계:

1. 브라우저는 GilJob Web/API HTTP 요청을 Caddy로 보냅니다.
2. API는 session/report token을 발급하되, 현재 runtime store는 process memory의 purpose-separated hash입니다. Postgres는 service/schema contract만 있고 insert/query wiring은 deferred입니다.
3. API는 LiveKit candidate token과 SpatialReal AvatarKit RTC viewer token을 분리해 발급합니다.
4. 브라우저는 Caddy를 통해 LiveKit media를 프록시하지 않고, API가 반환한 `LIVEKIT_PUBLIC_URL`로 LiveKit에 직접 연결합니다.
5. 후보자 답변 STT/분석은 `GilJobE`를 `services/analysis-engine`로 붙여 LiveKit audio/video track을 구독하는 구조입니다. 현재 browser는 development `/analysis/*` proxy로 subscriber start/stop/signals를 직접 호출합니다.
6. Production target은 `/analysis/*`를 public Caddy에서 숨기고 API broker가 session token + turn id를 검증한 뒤 analysis-engine을 호출하는 구조입니다.
7. `ai-engine`은 Gemini 질문 생성, Gemini TTS, SpatialReal session broker, SpatialReal LiveKit egress attempt를 담당합니다.
8. SpatialReal 아바타는 서버가 session token을 중개하고, 브라우저는 AvatarKit RTC renderer로 LiveKit room에 subscribe합니다.
9. SpatialReal 서버 SDK egress는 TTS audio를 SpatialReal에 보내고, SpatialReal이 LiveKit room에 avatar stream을 publish하는 구조입니다. 이때 `SPATIALREAL_RTC_LIVEKIT_URL`은 SpatialReal cloud에서 접근 가능한 public URL이어야 합니다.

위 다이어그램의 NOML 원본 파일: [`docs/architecture.noml`](docs/architecture.noml)

```noml
#.service: fill=#f5f5f5 stroke=#111111
#.external: fill=#ffffff stroke=#6b7280 dashed
#.media: fill=#e0f2fe stroke=#0369a1
#.secure: fill=#ecfdf5 stroke=#047857
#.future: fill=#fff7ed stroke=#c2410c dashed
#.store: fill=#f8fafc stroke=#475569
#.analysis: fill=#fef3c7 stroke=#a16207

[<external> 후보자 브라우저|
  /interviews/:id/room
  LiveKit candidate participant
  AvatarKit RTC viewer
  dev: /analysis poll/control
]

[<service> Caddy Ingress|
  :80/:443
  정적 Web 라우팅
  /api/* reverse proxy
  /analysis/* dev proxy (known gap)
  direct /ai,/tts,/avatar 차단
]

[<service> Web App|
  vanilla HTML/CSS/JS
  production room shell
  LiveKit 자동 join
  push-to-talk answer turn UI
  token-safe hidden diagnostics
]

[<secure> API Service|
  POST /api/sessions
  session/report token 발급
  in-process hash store (current)
  LiveKit candidate token 발급
  AvatarKit RTC viewer token 발급
  /api/interviews/:id/* broker
]

[<store> Postgres|
  service + schema contract
  durable session state 예정
  runtime persistence not wired yet
]

[<media> LiveKit Server|
  self-hosted signaling/media
  browser candidate participant
  analysis subscriber participant
  avatar publisher/viewer participants
  7880/tcp WebSocket
  7881/tcp ICE/TCP
  50000-50100/udp media
]

[<media> coturn|
  TURN/STUN relay container
  LiveKit TURN advertisement not wired
]

[<analysis> Analysis Engine Service\n(GilJobE)|
  LiveKit room subscribe participant
  candidate audio/video track consume
  GemmaNativeTranscriber STT
  transcript_full + structured signal emit
  Docker build currently blocked
]

[<service> AI Engine|
  Gemini next-question boundary
  Gemini native TTS voice boundary
  SpatialReal session broker
  SpatialReal LiveKit egress attempt
]

[<media> SpatialReal Cloud|
  session token API
  AvatarKit RTC assets/session
  TTS audio -> avatar stream
  LiveKit room publish
]

[<future> Authenticated Analysis Broker|
  move /analysis behind API
  validate session token + turn id
  hide transcript/signal controls
]

[<future> Main LLM / Interview Controller|
  질문 정책 orchestration 강화 예정
  후보자 답변 loop
  최종 report trigger
]

[후보자 브라우저] - HTTP app/API -> [Caddy Ingress]
[Caddy Ingress] - static pages -> [Web App]
[Caddy Ingress] - /api/* -> [API Service]
[Caddy Ingress] - /analysis/* dev proxy -> [Analysis Engine Service\n(GilJobE)]
[API Service] - schema contract only -> [Postgres]
[API Service] - candidate room URL + token -> [후보자 브라우저]
[API Service] - avatar viewer URL + token -> [후보자 브라우저]
[후보자 브라우저] - direct WebRTC publish/subscribe -> [LiveKit Server]
[후보자 브라우저] - AvatarKit RTC subscribe -> [LiveKit Server]
[후보자 브라우저] - dev analysis start/stop/signals -> [Analysis Engine Service\n(GilJobE)]
[LiveKit Server] - candidate audio/video tracks -> [Analysis Engine Service\n(GilJobE)]
[Analysis Engine Service\n(GilJobE)] - transcriptFull polled by browser -> [후보자 브라우저]
[후보자 브라우저] - lastAnswer via API broker -> [API Service]
[API Service] - next question / TTS / avatar session -> [AI Engine]
[AI Engine] - TTS audio / metadata -> [API Service]
[AI Engine] - session token / egress audio -> [SpatialReal Cloud]
[SpatialReal Cloud] - avatar stream publish -> [LiveKit Server]
[Authenticated Analysis Broker] - target production path -> [Analysis Engine Service\n(GilJobE)]
[AI Engine] - next question / policy update -> [Main LLM / Interview Controller]
[Main LLM / Interview Controller] - interview state/report -> [API Service]
[후보자 브라우저] - relay 필요 시 -> [coturn]
[LiveKit Server] - TURN strategy TBD -> [coturn]
```

렌더링 예시:

```bash
npx --yes nomnoml docs/architecture.noml docs/assets/architecture.svg
```

## Repository 구조

```text
apps/web/                       # 정적 web shell + LiveKit browser join UI
services/api/                   # session/token/API broker scaffold
services/ai-engine/             # Gemini question/TTS + SpatialReal avatar boundary
services/analysis-engine/       # GilJobE STT/multimodal analysis boundary
services/agent1/                # legacy/future multimodal placeholder
infra/docker-compose.yml        # base single-server stack
infra/docker-compose.media.yml  # LiveKit/coturn overlay
services/*/requirements.txt     # service별 Python dependency
requirements.txt                # 로컬 개발/검증용 Python dependency 집계 파일
apps/web/package.json           # browser vendor dependency lock
scripts/                        # smoke / browser join scripts
tests/contract/                 # API/Web/static contract tests
```

## 설치 / 실행 방법

### 0. 필요 도구

- Docker + Docker Compose plugin
- Python 3.12+
- Node.js 20+ / npm
- GitHub CLI (`gh`)는 PR 작업 시에만 필요

### 1. repository 준비

```bash
git clone https://github.com/GilJob-E/giljob-docker.git GilJob_v2
cd GilJob_v2
```

### 2. 환경변수 생성

```bash
cp .env.example .env
```

최소 local media 실행에 필요한 값:

```env
POSTGRES_PASSWORD=change-me-before-deploy
SESSION_TOKEN_HASH_SECRET=change-me-session-token-hash-secret
REPORT_TOKEN_HASH_SECRET=change-me-report-token-hash-secret
LIVEKIT_API_KEY=replace-me-local-only
LIVEKIT_API_SECRET=replace-me-local-only-minimum-32-bytes
TURN_REALM=turn.example.com
TURN_STATIC_AUTH_SECRET=replace-me-local-only-minimum-32-bytes
LIVEKIT_INTERNAL_URL=ws://livekit:7880
LIVEKIT_PUBLIC_URL=ws://127.0.0.1:7880
LIVEKIT_NODE_IP=127.0.0.1
```

실제 provider를 사용할 때 추가:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.5-flash
VOICE_PROVIDER=gemini
GEMINI_TTS_MODEL=gemini-3.1-flash-tts-preview
GEMINI_TTS_VOICE=Kore
AVATAR_PROVIDER=spatialreal
SPATIALREAL_API_KEY=...
SPATIALREAL_APP_ID=...
SPATIALREAL_AVATAR_ID=...
SPATIALREAL_RTC_EGRESS_ENABLED=true
SPATIALREAL_RTC_LIVEKIT_URL=wss://public-livekit.example.com
```

> `.env`는 절대 commit하지 않습니다. README와 test output에도 provider key, JWT, session token을 출력하지 않습니다.

### 3. Python requirements 설치 (로컬 개발/테스트용)

Docker build는 각 service의 `services/*/requirements.txt`를 사용합니다. 로컬에서 import/test를 확인하려면 루트 집계 파일을 사용할 수 있습니다.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

개별 service만 설치할 수도 있습니다.

```bash
pip install -r services/api/requirements.txt
pip install -r services/ai-engine/requirements.txt
pip install -r services/analysis-engine/requirements.txt
```

### 4. Web dependency lock 확인

```bash
cd apps/web
npm ci --omit=dev --ignore-scripts
npm run check:js
cd ../..
```

`@spatialwalk/avatarkit-rtc`는 현재 `livekit-client@2.16.1` 호환을 요구하므로 lockfile을 임의로 올리지 않습니다.

### 5. Compose config 확인

```bash
./scripts/smoke.sh config
```

또는 직접:

```bash
docker compose --env-file .env -f infra/docker-compose.yml config >/tmp/giljob-base.yml
docker compose --env-file .env -f infra/docker-compose.yml -f infra/docker-compose.media.yml config >/tmp/giljob-media.yml
```

### 6. Local media stack 실행

```bash
docker compose --env-file .env -f infra/docker-compose.yml -f infra/docker-compose.media.yml up -d --build
```

상태 확인:

```bash
docker compose --env-file .env -f infra/docker-compose.yml -f infra/docker-compose.media.yml ps
```

브라우저 확인:

```text
http://127.0.0.1/interviews/new
http://127.0.0.1/interviews/local-demo/lobby
http://127.0.0.1/interviews/local-demo/room
http://127.0.0.1/interviews/local-demo/report
```

종료:

```bash
docker compose --env-file .env -f infra/docker-compose.yml -f infra/docker-compose.media.yml down
```

### 7. Smoke 실행

```bash
KEEP_STACK=1 ./scripts/smoke.sh media-up
./scripts/smoke.sh browser-join
```

`KEEP_STACK=1`을 빼면 smoke 종료 후 stack을 내립니다.

## Cloudflare Tunnel / public LiveKit 메모

SpatialReal avatar egress는 SpatialReal cloud가 LiveKit에 직접 접속해야 합니다. 따라서 `SPATIALREAL_RTC_LIVEKIT_URL`은 `127.0.0.1`이 아니라 외부에서 접근 가능한 `wss://...`여야 합니다.

임시 개발용 quick tunnel 예시:

```bash
docker run -d --name giljob-v2-cloudflared-livekit \
  --restart unless-stopped \
  --network giljob-v2_default \
  cloudflare/cloudflared:latest \
  tunnel --no-autoupdate --url http://livekit:7880

docker logs giljob-v2-cloudflared-livekit
```

출력된 `https://...trycloudflare.com`를 `wss://...`로 바꿔 `.env`에 반영합니다.

```env
LIVEKIT_PUBLIC_URL=wss://...trycloudflare.com
SPATIALREAL_RTC_LIVEKIT_URL=wss://...trycloudflare.com
SPATIALREAL_RTC_EGRESS_ENABLED=true
```

영구 `livekit.giljob.org` route를 만들려면 Cloudflare API token에 최소한 Tunnel write와 DNS record write 권한이 필요합니다.

주의: Cloudflare Tunnel은 LiveKit signaling/WebSocket에는 유용하지만, WebRTC media path는 TURN 또는 public media ports가 추가로 필요할 수 있습니다.

## Port contract

| Port | 용도 |
|---|---|
| `80/tcp`, `443/tcp` | Caddy web/API ingress |
| `7880/tcp` | LiveKit API/WebSocket signaling |
| `7881/tcp` | LiveKit ICE/TCP fallback |
| `50000-50100/udp` | LiveKit WebRTC media range |
| `3478/udp+tcp`, `5349/tcp` | coturn relay |

## 보안 계약

반드시 유지해야 하는 계약:

- `/api/internal/*`는 외부에서 404로 차단합니다.
- direct `/ai/*`, `/tts/*`, `/avatar/*`는 외부에서 차단합니다.
- session/report public token은 create-session response에서만 반환합니다.
- 서버 저장소에는 raw token을 저장하지 않고 hash만 저장합니다.
- session token과 report token은 purpose-separated hash secret을 사용합니다.
- browser visible UI와 event log에는 raw JWT, `access_token`, `join_request`, `gj_session_*`, `gj_report_*`, provider key를 노출하지 않습니다.
- production/shared 환경에서는 `.env.example`의 `change-me`, `replace-me-local-only` 값을 그대로 쓰지 않습니다.

현재 known security gaps는 [`docs/reviews/main-branch-readiness-20260611.md`](docs/reviews/main-branch-readiness-20260611.md)에 정리되어 있습니다. 특히 `/analysis/*` public proxy, unauthenticated session/provider broker routes, and placeholder-secret startup checks are documentation-visible debt until code follow-up PRs close them.

## 검증 명령

```bash
python3 -m py_compile \
  services/api/server.py \
  services/api/app/livekit_tokens.py \
  services/api/app/token_contract.py \
  services/ai-engine/server.py \
  apps/web/server.py \
  services/agent1/server.py
node --check apps/web/static/app.js
node --check scripts/browser-join-smoke.mjs
(cd apps/web && npm ci --omit=dev --ignore-scripts)
(cd apps/web && npm run check:js)
(cd apps/web && npm audit --omit=dev --audit-level=high)
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/contract -p 'test_*_contract.py' -v

# Known failing gates at reviewed main commit 34403b7; keep them visible until fixed.
docker build -q services/analysis-engine >/tmp/giljob-analysis-engine-image.txt
npx --yes pyright
```

원격 single-server에서 확인할 때는 `/home/hoddukzoa/GilJob_v2` 기준으로 실행합니다. 기존 `/home/hoddukzoa/GilJob`는 건드리지 않습니다.

## 관련 문서

- [`DESIGN.md`](DESIGN.md)
- [`docs/architecture.noml`](docs/architecture.noml)
- [`docs/demo-screenshots.md`](docs/demo-screenshots.md)
- [`docs/reviews/main-branch-readiness-20260611.md`](docs/reviews/main-branch-readiness-20260611.md)
- [`docs/implementation-plan.md`](docs/implementation-plan.md)
- [`docs/runbooks/local-livekit-media.md`](docs/runbooks/local-livekit-media.md)
- [`docs/runbooks/tts-avatar-contract.md`](docs/runbooks/tts-avatar-contract.md)
- [`docs/runbooks/verification.md`](docs/runbooks/verification.md)
- [`docs/decisions/0001-state-stack.md`](docs/decisions/0001-state-stack.md)
- [`docs/decisions/0002-ingress-stack.md`](docs/decisions/0002-ingress-stack.md)

## 다음 구현 후보

1. SpatialReal RTC egress 실패 원인 세분화 및 provider error telemetry 강화
2. TURN/public media path 구성 검증
3. `services/analysis-engine` LiveKit subscriber runtime loop 강화
4. analysis-engine → ai-engine signal delivery 안정화
5. Main LLM / InterviewController turn orchestration 강화
6. final report placeholder를 실제 report generator로 교체
