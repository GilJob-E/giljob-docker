# GilJob v2

GilJob v2는 **한 대의 서버에서 Docker Compose로 실행하는 self-hosted AI 면접 시스템 scaffold**입니다. 현재 목표는 전체 제품을 한 번에 구현하는 것이 아니라, production에 가까운 라우트/보안/미디어 경계 위에 LiveKit 기반 면접룸의 최소 실행 단위를 세우는 것입니다.

![GilJob v2 아키텍처](docs/assets/architecture.svg)

> 중요: 이 repository/worktree는 기존 `/home/hoddukzoa/GilJob`와 분리된 v2 작업 공간입니다. 기존 GilJob 폴더를 복사·삭제·수정하지 않습니다.

## 현재 상태

구현됨:

- 단일 서버 Docker Compose 기반 scaffold
- Caddy ingress
- Python stdlib 기반 `api`, `web`, `ai-engine`, `agent1` placeholder service
- `services/analysis-engine` GilJobE dependency/health scaffold
- Postgres service 및 token hash 저장 계약
- optional self-hosted LiveKit/coturn media overlay
- `POST /api/sessions` 후보자 session 생성
- LiveKit candidate join token 발급
- production 형태의 interview routes
  - `/interviews/new`
  - `/interviews/:id/lobby`
  - `/interviews/:id/room`
  - `/interviews/:id/report`
- 실제 room route에서 LiveKit 자동 join
- room 내부 prejoin/setup UI 제거
- 로컬 Whisper/STT service 제거 완료; STT는 `GilJobE` 기반 `services/analysis-engine` 경계로 연결 예정
- token redaction 및 raw token 비노출 contract test

아직 범위 밖:

- CV/job parsing
- 실제 Main LLM 전체 orchestration loop
- SpatialReal avatar 및 ElevenLabs TTS 본구현. Gemini TTS provider는 room voice boundary에 연결되어 있으며, provider env/security contract는 [`docs/runbooks/tts-avatar-contract.md`](docs/runbooks/tts-avatar-contract.md)에 정의되어 있습니다.
- `GilJobE` 기반 `services/analysis-engine` LiveKit subscribe 실연결
- 최종 report 생성
- production domain/TLS/hardening
- Redis 기반 event bus 전환

## Production UX 기준

현재 라우트 책임은 아래처럼 나눕니다.

| Route | 책임 | 현재 상태 |
|---|---|---|
| `/interviews/new` | CV, 직무 링크, persona 선택 진입점 | placeholder |
| `/interviews/:id/lobby` | device readiness, 입장 전 확인 | placeholder |
| `/interviews/:id/room` | 실제 면접룸 | LiveKit 자동 join + room shell |
| `/interviews/:id/report` | 면접 종료 후 report | placeholder |

`room`은 Zoom/Google Meet처럼 “이미 방에 들어온 화면”이어야 합니다. 따라서 room 내부에는 prejoin form, endpoint 입력, “Join room” 버튼, 개발용 긴 설명문을 두지 않습니다. 입장 준비는 lobby가 담당하고, room은 mic/camera/leave/report control과 면접 상태 패널만 보여줍니다.

## 아키텍처 요약

핵심 경계:

1. 브라우저는 GilJob Web/API HTTP 요청을 Caddy로 보냅니다.
2. API는 session/report token을 발급하되, 서버 쪽에는 purpose-separated hash만 저장하는 계약을 유지합니다.
3. API는 LiveKit candidate token을 발급합니다.
4. 브라우저는 Caddy를 통해 LiveKit media를 프록시하지 않고, API가 반환한 `LIVEKIT_PUBLIC_URL`로 LiveKit에 직접 연결합니다.
5. 로컬 Whisper/STT 경계는 제거되었습니다. 후보자 답변 STT는 `GilJobE`를 `services/analysis-engine`로 붙여 LiveKit audio/video track을 구독하는 구조로 진행합니다.
6. SpatialReal/Avatar, TTS 출력, 최종 report generator는 아직 future slice입니다. Phase 1에서는 TTS/Avatar provider 환경변수와 secret/token surface contract만 고정합니다. 자세한 내용은 [`docs/runbooks/tts-avatar-contract.md`](docs/runbooks/tts-avatar-contract.md)를 봅니다.

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
  /interviews/new
  /interviews/:id/lobby
  /interviews/:id/room
  /interviews/:id/report
]

[<service> Caddy Ingress|
  :80/:443
  정적 Web 라우팅
  /api/* reverse proxy
  /api/internal/* 차단
]

[<service> Web App|
  vanilla HTML/CSS/JS
  production route shell
  room 진입 시 LiveKit 자동 join
  push-to-talk answer turn UI
  token-safe hidden diagnostics
]

[<secure> API Service|
  POST /api/sessions
  session/report token 발급
  purpose-separated hash contract
  LiveKit candidate token 발급
  LiveKit analyzer token 발급 예정
]

[<store> Postgres|
  향후 durable session state
  token hash only
  raw public token 저장 금지
]

[<media> LiveKit Server|
  self-hosted signaling/media
  browser candidate participant
  hidden analysis participant
  7880/tcp WebSocket
  7881/tcp ICE/TCP
  50000-50100/udp media
]

[<media> coturn|
  direct TURN/STUN overlay
  3478 udp/tcp
  5349 tcp
]

[<analysis> Analysis Engine Service\n(GilJobE)|
  services/analysis-engine 예정
  LiveKit room subscribe participant
  candidate audio/video track consume
  GemmaNativeTranscriber STT
  nonverbal/vision windowing
  transcript_full + structured signal emit
]

[<service> AI Engine|
  Gemini next-question boundary
  Gemini native TTS voice boundary
  analysis signal + transcript 입력
  질문 생성 / turn policy
]


[<future> Avatar / SpatialReal|
  면접관 화면 participant
  LiveKit publish 후보
  interviewer voice/video output
]

[<future> Main LLM / Interview Controller|
  질문 정책 orchestration
  후보자 답변 loop
  최종 report trigger
]

[후보자 브라우저] - HTTP app/API -> [Caddy Ingress]
[Caddy Ingress] - static pages -> [Web App]
[Caddy Ingress] - /api/sessions -> [API Service]
[API Service] - token hash 저장 -> [Postgres]
[API Service] - candidate room URL + token -> [후보자 브라우저]
[API Service] - analyzer subscribe token -> [Analysis Engine Service\n(GilJobE)]
[후보자 브라우저] - direct WebRTC publish/subscribe -> [LiveKit Server]
[후보자 브라우저] - push-to-talk turn_start/turn_end -> [API Service]
[후보자 브라우저] - relay 필요 시 -> [coturn]
[LiveKit Server] - TURN boundary -> [coturn]
[LiveKit Server] - candidate audio/video tracks -> [Analysis Engine Service\n(GilJobE)]
[Analysis Engine Service\n(GilJobE)] - transcript_full + multimodal signals -> [AI Engine]
[Analysis Engine Service\n(GilJobE)] - structured session events -> [API Service]
[AI Engine] - next question / policy update -> [Main LLM / Interview Controller]
[Main LLM / Interview Controller] - interview state/report -> [API Service]
[Main LLM / Interview Controller] - interviewer utterance -> [Avatar / SpatialReal]
[Avatar / SpatialReal] - interviewer participant media -> [LiveKit Server]
```

렌더링 예시:

```bash
npx nomnoml docs/architecture.noml docs/assets/architecture.svg
```

## Repository 구조

```text
apps/web/                 # 정적 web shell + LiveKit browser join UI
services/api/             # session/token API scaffold
services/ai-engine/       # Gemini next-question + Gemini TTS provider boundary
services/analysis-engine/ # GilJobE STT/multimodal analysis boundary
services/agent1/          # legacy/future multimodal placeholder
infra/docker-compose.yml  # base single-server stack
infra/docker-compose.media.yml # LiveKit/coturn overlay
docs/                     # planning, ADR, runbook, source docs
scripts/                  # smoke / browser join scripts
tests/contract/           # API/Web/static contract tests
```

## 빠른 시작

### 1. 설정 확인

```bash
./scripts/smoke.sh config
```

이 명령은 base compose config와 media overlay fail-closed contract를 확인합니다. media overlay는 `LIVEKIT_PUBLIC_URL` 등 필수 값이 없으면 render되지 않아야 합니다.

### 2. Local media stack 실행

```bash
KEEP_STACK=1 ./scripts/smoke.sh media-up
```

실행되는 주요 service:

- `postgres`
- `api`
- `web`
- `livekit`
- `coturn`

`KEEP_STACK=1`을 빼면 smoke 종료 후 stack을 내립니다.

### 3. Browser join smoke

```bash
./scripts/smoke.sh browser-join
```

이 smoke는 Caddy까지 띄운 뒤 headless Chrome/Playwright로 `/interviews/local-demo/room`에 들어가 LiveKit join/leave를 검증합니다.

## 수동 실행

`.env.example`을 참고해 `.env`를 만들거나 필요한 env를 export합니다.

```bash
cp .env.example .env
cd infra
docker compose -f docker-compose.yml -f docker-compose.media.yml up -d --build
```

브라우저 확인:

```text
http://127.0.0.1/interviews/new
http://127.0.0.1/interviews/local-demo/lobby
http://127.0.0.1/interviews/local-demo/room
http://127.0.0.1/interviews/local-demo/report
```

같은 서버에서 직접 LiveKit을 확인하는 local 기본값:

```env
LIVEKIT_INTERNAL_URL=ws://livekit:7880
LIVEKIT_PUBLIC_URL=ws://127.0.0.1:7880
LIVEKIT_NODE_IP=127.0.0.1
```

외부 브라우저에서 접속하려면 `LIVEKIT_PUBLIC_URL`과 `LIVEKIT_NODE_IP`를 그 브라우저가 접근 가능한 서버 주소로 바꾸고, LiveKit/TURN port를 열어야 합니다.

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
- session/report public token은 create-session response에서만 반환합니다.
- 서버 저장소에는 raw token을 저장하지 않고 hash만 저장합니다.
- session token과 report token은 purpose-separated hash secret을 사용합니다.
- browser visible UI와 event log에는 raw JWT, `access_token`, `join_request`, `gj_session_*`, `gj_report_*`를 노출하지 않습니다.
- production/shared 환경에서는 `.env.example`의 `change-me`, `replace-me-local-only` 값을 그대로 쓰지 않습니다.

## 검증 명령

```bash
node --check apps/web/static/app.js
node --check scripts/browser-join-smoke.mjs
python3 -m unittest discover -s tests/contract -v
(cd apps/web && npm run check:js)
(cd apps/web && npm audit --omit=dev --audit-level=high)
npx --yes pyright
```

원격 single-server에서 확인할 때는 `/home/hoddukzoa/GilJob_v2` 기준으로 실행합니다. 기존 `/home/hoddukzoa/GilJob`는 건드리지 않습니다.

## 관련 문서

- [`DESIGN.md`](DESIGN.md)
- [`docs/architecture.noml`](docs/architecture.noml)
- [`docs/demo-screenshots.md`](docs/demo-screenshots.md)
- [`docs/implementation-plan.md`](docs/implementation-plan.md)
- [`docs/runbooks/local-livekit-media.md`](docs/runbooks/local-livekit-media.md)
- [`docs/runbooks/verification.md`](docs/runbooks/verification.md)
- [`docs/decisions/0001-state-stack.md`](docs/decisions/0001-state-stack.md)
- [`docs/decisions/0002-ingress-stack.md`](docs/decisions/0002-ingress-stack.md)

## 다음 구현 후보

1. `services/analysis-engine` LiveKit subscriber runtime loop 구현
2. analyzer token API contract 추가
3. analysis-engine → ai-engine signal delivery 연결
4. TTS / SpatialReal avatar 연결
5. Main LLM / InterviewController turn orchestration 강화
6. final report placeholder를 실제 report generator로 교체
