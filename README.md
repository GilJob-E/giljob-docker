# GilJob v2

GilJob v2는 **한 대의 서버에서 Docker Compose로 실행하는 self-hosted AI 면접 시스템 scaffold**입니다. 현재 목표는 전체 제품을 한 번에 구현하는 것이 아니라, production에 가까운 라우트/보안/미디어 경계 위에 LiveKit 기반 면접룸의 최소 실행 단위를 세우는 것입니다.

![GilJob v2 아키텍처](docs/assets/architecture.svg)

> 중요: 이 repository/worktree는 기존 `/home/hoddukzoa/GilJob`와 분리된 v2 작업 공간입니다. 기존 GilJob 폴더를 복사·삭제·수정하지 않습니다.

## 현재 상태

구현됨:

- 단일 서버 Docker Compose 기반 scaffold
- Caddy ingress
- Python stdlib 기반 `api`, `web`, `ai-engine`, `agent1` placeholder service
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
- LiveKit 연결 직후 `/stt/warmup`으로 local Whisper 모델을 미리 로드하고, 답변 중 누적 browser audio를 `/stt/transcribe`로 보내는 실시간 임시 전사와 답변 종료 후 최종 전사 경계
- `Systran/faster-whisper-large-v3` 기반 `stt-whisper` service
- Docker Compose에서 STT service를 host GPU `1`에 고정
- token redaction 및 raw token 비노출 contract test

아직 범위 밖:

- CV/job parsing
- 실제 Main LLM 전체 orchestration loop
- SpatialReal / ElevenLabs avatar 또는 TTS
- Agent1 multimodal 분석 실연결
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
5. LiveKit 연결이 완료되면 브라우저가 `/stt/warmup`을 비동기로 호출해 Whisper 모델 cold start를 먼저 당깁니다. 이후 후보자가 답변하는 동안 브라우저가 누적 audio를 몇 초 단위로 `/stt/transcribe`에 보내 임시 전사를 표시하고, 답변 종료 버튼을 누르면 같은 답변 audio를 최종 전사로 확정합니다. `stt-whisper`는 host GPU `1`에서 local faster-whisper 전사를 수행합니다.
6. Agent1 multimodal module, TTS/avatar, 최종 report generator는 아직 future slice입니다.

위 다이어그램의 NOML 원본 파일: [`docs/architecture.noml`](docs/architecture.noml)

```noml
#.service: fill=#f5f5f5 stroke=#111111
#.external: fill=#ffffff stroke=#6b7280 dashed
#.media: fill=#e0f2fe stroke=#0369a1
#.secure: fill=#ecfdf5 stroke=#047857
#.future: fill=#fff7ed stroke=#c2410c dashed
#.store: fill=#f8fafc stroke=#475569

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
  token-safe hidden diagnostics
]

[<secure> API Service|
  POST /api/sessions
  session/report token 발급
  purpose-separated hash contract
  LiveKit candidate token 발급
]

[<store> Postgres|
  향후 durable session state
  token hash only
  raw public token 저장 금지
]

[<media> LiveKit Server|
  self-hosted signaling/media
  7880/tcp WebSocket
  7881/tcp ICE/TCP
  50000-50100/udp media
]

[<media> coturn|
  direct TURN/STUN overlay
  3478 udp/tcp
  5349 tcp
]

[<service> AI Engine|
  Gemini next-question boundary
  full orchestration은 향후
]

[<service> STT Whisper|
  Systran/faster-whisper-large-v3
  host GPU 1 고정
  /stt/transcribe
]

[<future> Agent1 Multimodal Module|
  향후 raw AV windowing
  structured signal only
  token/media 직접 노출 금지
]

[<future> Main LLM / Interview Controller|
  향후 질문 정책
  후보자 답변 loop
  최종 report trigger
]

[후보자 브라우저] - HTTP app/API -> [Caddy Ingress]
[Caddy Ingress] - static pages -> [Web App]
[Caddy Ingress] - /api/sessions -> [API Service]
[API Service] - token hash 저장 -> [Postgres]
[API Service] - internal URL로 room/token 발급 -> [LiveKit Server]
[API Service] - public room URL + candidate token -> [후보자 브라우저]
[후보자 브라우저] - direct WebRTC signaling/media -> [LiveKit Server]
[후보자 브라우저] - warmup + partial/final answer audio upload -> [STT Whisper]
[STT Whisper] - partial/final transcript text -> [후보자 브라우저]
[후보자 브라우저] - lastAnswer -> [AI Engine]
[후보자 브라우저] - relay 필요 시 -> [coturn]
[LiveKit Server] - TURN boundary -> [coturn]
[AI Engine] - 향후 participant subscribe/publish -> [LiveKit Server]
[Agent1 Multimodal Module] - 향후 media observation -> [LiveKit Server]
[Agent1 Multimodal Module] - structured signal -> [Main LLM / Interview Controller]
[Main LLM / Interview Controller] - 향후 interview state/report -> [API Service]

```

렌더링 예시:

```bash
npx nomnoml docs/architecture.noml docs/assets/architecture.svg
```

## Repository 구조

```text
apps/web/                 # 정적 web shell + LiveKit browser join UI
services/api/             # session/token API scaffold
services/ai-engine/       # Gemini next-question provider boundary
services/stt-whisper/     # local faster-whisper STT, host GPU 1
services/agent1/          # 향후 multimodal module placeholder
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
- `stt-whisper`

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
| internal `8200/tcp` | `stt-whisper` transcription service behind Caddy `/stt/*` |

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

1. lobby에 device readiness check 추가
2. fake 3-turn interview loop
3. Agent1 multimodal signal schema 정의
4. TTS / SpatialReal avatar 연결
5. Main LLM / InterviewController turn orchestration 강화
6. final report placeholder를 실제 report generator로 교체
