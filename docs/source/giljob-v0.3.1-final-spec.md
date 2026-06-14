# GilJob v2 — Single-Server Docker 상세 기술명세서

- 문서 버전: `v0.3.1-single-server-docker-high3-closed`
- 작성 시각: `2026-05-30 13:28 KST`
- 상태: **MVP/졸작 데모 기준 채택안 — reviewer High 3개 패치 반영본**
- 이전 방향: `Frontend serverless + Worker + Local AI Engine`
- 변경 방향: **전부 한 서버 Docker Compose 배포**
- 핵심 원칙: **Single server, multi-container, service-boundary 유지**

---

> Archive note: this is a historical source snapshot from 2026-05-30, not the active Realtime architecture. Current runtime/docs use OpenAI Realtime-only live interviewer voice and do not support a secondary LLM/TTS fallback.

## 0.1 v0.3 패치 요약

Reviewer가 지적한 P0/P1 blocker를 반영해 다음을 명세에 고정했다.

- **Network/Port Matrix 통일**: LiveKit RTC UDP range와 coturn relay range를 분리하되, 방화벽/보안그룹/테스트 기준을 하나의 표로 통합했다.
- **Internal API public 차단**: Caddy에서 `/api/internal/*`를 먼저 404로 차단하고, API 서버도 `X-GilJob-Internal-Token` 또는 HMAC 서명을 검증하도록 했다.
- **Token contract 완성**: session token/report token을 opaque bearer token으로 정의하고, scope/TTL/hash 저장/발급 시점을 고정했다.
- **StateCoordinator CAS 실체화**: `state + state_version` 조건부 update, allowed transition table, idempotent event handling SQL 흐름을 추가했다.
- **Redis backpressure 수치화**: stream maxlen, TTL, drop/retry/DLQ 정책을 event type별로 추가했다.
- **Docker smoke/healthcheck 정정**: host에 publish되지 않은 `expose` 포트를 `localhost`로 때리는 검증을 제거하고, public route + `docker compose exec` 기준으로 바꿨다.
- **재현성 보강**: `latest` image tag를 금지하고 `.env`에서 이미지 버전을 pin하도록 변경했다.

---

## 0.2 v0.3.1 High 3개 패치 요약

Reviewer 재리뷰 결과 `PASS_WITH_CONCERNS`로 남은 High 3개를 닫기 위해 다음을 추가 고정한다.

- **H-01 Token TTL/signing 일관화**: `.env` TTL과 token contract를 session 2h/report 30d로 통일하고, session/report token hash secret을 분리한다.
- **H-02 Health smoke route 통일**: public health endpoint는 `/healthz`/`/readyz`만 사용한다. API-prefixed health smoke path는 명세 endpoint가 아니므로 smoke/runbook에서 제거한다.
- **H-03 Initial state/transition seed 명확화**: `POST /api/sessions`는 token 발급과 hash 저장이 끝난 뒤 외부 observable state로 `WAITING_FRONTEND`를 반환한다. `CREATED`는 transaction-local/audit용 transient state이며, allowed transition seed는 wildcard 없이 concrete row로 확장한다.

---

## 0. 최종 결정

GilJob v2 MVP는 **한 서버에서 Docker Compose로 전체 시스템을 실행**한다.

단, 이 결정은 “모든 코드를 하나의 모놀리식 프로세스로 합친다”는 뜻이 아니다. 서비스 경계는 유지한다.

```txt
✅ 한 서버
✅ docker compose
✅ 서비스별 컨테이너 분리
✅ 내부 Docker network 사용
✅ Caddy/Nginx reverse proxy로 public ingress 통합
✅ LiveKit + coturn self-host 기본
✅ AI Engine/Agent1/DB/Redis는 외부 직접 노출 금지
```

---

## 1. 왜 갈아엎는가

기존 split deployment 구조는 장기 실서비스에는 좋지만, 지금 졸작 MVP에는 복잡도가 높다.

기존 split 구조의 문제:

```txt
Cloudflare Pages
Cloudflare Worker
LiveKit Cloud
Local AI Engine
SpatialReal external API
```

이렇게 경계가 많아지면 다음 문제가 생긴다.

- Worker state와 Engine state 불일치
- local engine 연결/터널/방화벽 문제
- CORS/auth/token broker 복잡도 증가
- 장애 원인 추적 어려움
- 졸작 시연 직전 외부 서비스 의존성 증가
- reviewer가 지적한 session coordination 문제가 더 커짐

따라서 MVP에서는 한 서버에 모아 다음을 얻는다.

- 디버깅 단순화
- 재현 가능한 데모 환경
- 상태 저장소 단일화
- 네트워크 경계 축소
- 구현 속도 향상
- 발표용 아키텍처 설명 명확화

---

## 2. 제품 목표

GilJob v2는 실시간 AI 모의면접 시스템이다.

지원자는 웹 브라우저에서 면접을 시작하고, 아바타 면접관이 실시간으로 질문한다. 지원자의 음성/영상은 WebRTC로 서버에 전달되고, 서버는 STT와 멀티모달 분석을 병렬 실행한다. Agent2는 전사와 멀티모달 신호를 바탕으로 다음 질문을 생성하고, SpatialReal 아바타가 이를 말한다. 세션 종료 후 리포트가 생성된다.

### 2.1 MVP 성공 조건

MVP는 다음을 만족해야 한다.

- public HTTPS URL로 접속 가능
- 브라우저에서 카메라/마이크 권한 획득
- LiveKit room 입장
- 서버 AI Engine이 candidate audio/video track subscribe
- STT final transcript 생성
- Agent1이 최소 nonverbal signal 생성
- Agent2가 다음 질문 생성
- SpatialReal 또는 text/TTS fallback으로 질문 재생
- 최소 3턴 이상 면접 진행
- 종료 후 report 생성
- `docker compose up -d`로 재현 가능

### 2.2 발표에서 보여줄 기술 포인트

- Docker 기반 전체 시스템 배포
- WebRTC 기반 실시간 audio/video transport
- STT와 멀티모달 Agent1 병렬 처리
- Agent1/Agent2 역할 분리
- 아바타 면접관 응답 loop
- 세션 상태머신과 이벤트 버스
- 리포트 생성
- 장애 fallback 설계

---

## 3. 비목표

v0.3.1 MVP에서 하지 않는다.

- 완전한 multi-tenant SaaS
- 대규모 autoscaling
- multi-region 배포
- Kubernetes
- 실제 채용 합격/불합격 판정
- raw media 장기 저장
- 얼굴 인식 기반 신원 확인
- 복잡한 결제/구독
- split frontend/backend cloud deployment
- 모든 LLM/비전 모델 자체 호스팅 강제

---

## 4. 전체 아키텍처

## 4.1 High-level diagram

```txt
[Candidate Browser]
  │
  │ HTTPS / WSS / WebRTC
  ▼
[Public Domain: https://giljob.example.com]
  │
  ▼
[Caddy Reverse Proxy Container]
  ├─ /                         → frontend container
  ├─ /api/*                    → api-server container
  ├─ /healthz                  → api-server health aggregate
  ├─ /livekit/* or :7880       → livekit server
  └─ TURN/STUN UDP/TCP ports   → coturn host/network

[Docker Compose Internal Network]
  ├─ frontend
  ├─ api-server
  ├─ ai-engine
  ├─ agent1-multimodal
  ├─ redis
  ├─ postgres
  ├─ livekit
  ├─ coturn
  └─ optional: adminer/prometheus/grafana for dev only

[External APIs]
  ├─ SpatialReal API
  ├─ LLM provider, if Agent2 cloud model used
  ├─ STT/TTS provider, if cloud used
  └─ optional object storage, if later enabled
```

## 4.2 핵심 원칙

### 원칙 A — 하나의 서버, 여러 컨테이너

서버는 하나지만 서비스는 분리한다.

```txt
frontend ≠ api-server ≠ ai-engine ≠ agent1 ≠ livekit ≠ db
```

이유:

- dependency 충돌 방지
- 로그 분리
- restart 범위 축소
- 나중에 split deployment로 이전 가능
- reviewer가 말한 control plane을 명확히 하기 쉬움

### 원칙 B — public ingress는 reverse proxy 하나로 통합

외부에서 직접 접근 가능한 포트는 최소화한다.

외부 허용:

```txt
80/tcp    HTTP → HTTPS redirect
443/tcp   HTTPS frontend/API/WSS
7880/tcp  LiveKit websocket, proxy 또는 direct
UDP media port range, if self-host LiveKit
TURN ports, if coturn
```

외부 금지:

```txt
postgres:5432
redis:6379
ai-engine internal port
agent1 internal port
internal debug API
```

### 원칙 C — 브라우저는 API와 LiveKit만 본다

브라우저는 `ai-engine`이나 `agent1`을 직접 호출하지 않는다.

```txt
Browser → API server → session/token/status/report
Browser → LiveKit → media transport
AI Engine → LiveKit → media subscribe/publish
AI Engine → Agent1 internal HTTP/gRPC
AI Engine → SpatialReal external API
```

### 원칙 D — LiveKit self-host를 기본으로 한다

사용자가 “전부 Docker 한 서버”를 원했으므로 기본은 LiveKit self-host다.

단, WebRTC는 UDP/TURN/방화벽 때문에 막힐 수 있다. 따라서 코드는 LiveKit URL만 바꾸면 Cloud fallback이 가능하도록 설계한다. 하지만 문서의 기본 배포는 self-host다.

### 원칙 E — secret은 서버 컨테이너에만 존재

frontend build artifact에 secret이 들어가면 안 된다.

금지:

```txt
VITE_LIVEKIT_API_SECRET
VITE_SPATIALREAL_API_KEY
VITE_LLM_API_KEY
VITE_DB_PASSWORD
```

허용:

```txt
VITE_PUBLIC_API_BASE_URL
VITE_PUBLIC_LIVEKIT_URL
VITE_PUBLIC_APP_NAME
```

LiveKit participant token은 `/api/sessions`에서 짧게 발급한다.

---

## 5. 서버 요구사항

## 5.1 최소 개발/데모 서버

```txt
CPU: 8 cores 권장, 최소 4 cores
RAM: 16GB 권장, 최소 8GB
Disk: 80GB 이상
OS: Ubuntu 22.04/24.04 LTS 권장
Docker: 24+
Docker Compose: v2+
Public IP: 권장/사실상 필수
Domain: 권장
TLS: Caddy 자동 발급 or Nginx + certbot
```

## 5.2 AI/멀티모달 성능 기준

Agent1이 local multimodal model/vLLM을 쓴다면 추가 요구사항:

```txt
GPU: NVIDIA GPU 권장
VRAM: 모델에 따라 12GB~24GB+
CUDA driver: host에 설치
Docker NVIDIA runtime 필요
```

GPU가 없으면 MVP에서는 다음 중 하나를 선택한다.

- Agent1 FakeProvider로 시작
- Agent1 cloud provider 사용
- Agent1을 lightweight heuristic/demo mode로 제한
- evaluation window는 느린 background mode로 처리

## 5.3 네트워크 요구사항 — v0.3 통합 Port Matrix

LiveKit self-host에서 가장 자주 터지는 지점은 WebRTC UDP/TURN 포트다. v0.3부터는 LiveKit RTC media range와 coturn relay range를 **의도적으로 분리**하고, 둘 다 방화벽/보안그룹에 명시한다.

### 5.3.1 Public ingress / firewall matrix

| 용도 | Protocol | Port/Range | Host process/container | Public open | 비고 |
|---|---:|---:|---|---|---|
| HTTP redirect | TCP | 80 | caddy | yes | TLS redirect only |
| HTTPS app/API | TCP | 443 | caddy | yes | frontend + `/api/*` |
| LiveKit WSS/API | TCP | 7880 | livekit or caddy→livekit | yes | `livekit.example.com` |
| LiveKit TCP fallback | TCP | 7881 | livekit | yes | WebRTC TCP fallback |
| LiveKit RTC media | UDP | 50000-50100 | livekit | yes | `livekit.yaml`와 compose 동일 |
| STUN/TURN | UDP | 3478 | coturn | yes | primary TURN/STUN |
| TURN TCP fallback | TCP | 3478 | coturn | yes | restrictive network fallback |
| TURN TLS | TCP | 5349 | coturn | optional yes | 필요 시 cert 설정 |
| TURN relay media | UDP/TCP | 49160-49200 | coturn | yes | `turnserver.conf`와 방화벽 동일 |
| Postgres | TCP | 5432 | postgres | **no** | Docker internal only |
| Redis | TCP | 6379 | redis | **no** | Docker internal only |
| AI Engine | TCP | 8100 | ai-engine | **no** | Docker internal only |
| Agent1 | TCP | 8010 | agent1 | **no** | Docker internal only |

### 5.3.2 포트 정합성 불변조건

- `LIVEKIT_RTC_UDP_PORT_START/END` = `livekit.yaml rtc.port_range_start/end` = compose `50000-50100/udp` = 서버 방화벽 open range.
- `TURN_RELAY_PORT_START/END` = `turnserver.conf min-port/max-port` = 서버 방화벽 open range.
- LiveKit RTC range와 TURN relay range는 겹치지 않게 둔다. 이 문서의 기본값은 LiveKit `50000-50100/udp`, coturn `49160-49200/udp,tcp`이다.
- 데모 전에는 최소 2개 네트워크에서 확인한다: 같은 Wi-Fi, 모바일 hotspot/5G.

### 5.3.3 데모 전 WebRTC 네트워크 체크

```bash
# 서버에서 리스닝 확인
ss -lntup | grep -E ':(80|443|7880|7881|3478|5349)\b|50000|49160' || true

# Docker 상태
docker compose ps livekit coturn caddy
docker compose logs --tail=100 livekit
docker compose logs --tail=100 coturn
```

서버/클라우드 방화벽에서 UDP range를 열 수 없으면 WebRTC 연결이 불안정하다. 이 경우에도 코드는 LiveKit URL/env만 바꿔 LiveKit Cloud fallback을 쓸 수 있게 유지한다.

---

## 6. Docker Compose 서비스 구성

## 6.1 서비스 목록

필수 서비스:

```txt
caddy              public reverse proxy + TLS
frontend           static frontend
api                session/token/report/control API
ai-engine          realtime orchestrator
agent1             multimodal analyzer service
redis              runtime event bus / queues / ephemeral state
postgres           durable sessions/reports/signals
livekit            WebRTC SFU
coturn             TURN/STUN server
```

선택 서비스:

```txt
prometheus         metrics, dev/prod optional
grafana            dashboard, dev/prod optional
adminer            DB browser, dev only, public 노출 금지
minio              local object storage, only if storing consented artifacts
```

## 6.2 compose 파일 위치

권장 repo layout:

```txt
giljob/
  docker-compose.yml
  .env.example
  .env                      # git ignore
  README.md

  infra/
    Caddyfile
    livekit.yaml
    turnserver.conf
    postgres/
      init.sql
    scripts/
      backup-db.sh
      restore-db.sh
      healthcheck.sh

  frontend/
    Dockerfile
    package.json
    src/

  backend/
    api/
      Dockerfile
      pyproject.toml
      src/giljob_api/
    ai-engine/
      Dockerfile
      pyproject.toml
      src/giljob_engine/
    agent1-multimodal/
      Dockerfile
      pyproject.toml
      src/giljob_agent1/

  packages/
    shared-schemas/
      python/
      typescript/

  docs/
    architecture.md
    api-contract.md
    deployment-single-server-docker.md
    realtime-protocol.md
    security-privacy.md
    demo-runbook.md
```

## 6.3 docker-compose.yml 초안

```yaml
name: giljob

services:
  caddy:
    image: caddy:2.8-alpine
    container_name: giljob-caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./infra/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      frontend:
        condition: service_started
      api:
        condition: service_healthy
      livekit:
        condition: service_started
    networks:
      - public
      - internal

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
      args:
        VITE_PUBLIC_API_BASE_URL: ${PUBLIC_API_BASE_URL}
        VITE_PUBLIC_LIVEKIT_URL: ${PUBLIC_LIVEKIT_URL}
    container_name: giljob-frontend
    restart: unless-stopped
    expose:
      - "80"
    networks:
      - internal

  api:
    build:
      context: ./backend/api
      dockerfile: Dockerfile
    container_name: giljob-api
    restart: unless-stopped
    env_file:
      - .env
    expose:
      - "8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      livekit:
        condition: service_started
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/healthz"]
      interval: 10s
      timeout: 3s
      retries: 10
    networks:
      - internal

  ai-engine:
    build:
      context: ./backend/ai-engine
      dockerfile: Dockerfile
    container_name: giljob-ai-engine
    restart: unless-stopped
    env_file:
      - .env
    depends_on:
      api:
        condition: service_healthy
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
      agent1:
        condition: service_healthy
      livekit:
        condition: service_started
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8100/healthz"]
      interval: 10s
      timeout: 3s
      retries: 10
    expose:
      - "8100"
    networks:
      - internal

  agent1:
    build:
      context: ./backend/agent1-multimodal
      dockerfile: Dockerfile
    container_name: giljob-agent1
    restart: unless-stopped
    env_file:
      - .env
    expose:
      - "8010"
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8010/healthz"]
      interval: 10s
      timeout: 3s
      retries: 10
    networks:
      - internal
    # If GPU is needed later:
    # deploy:
    #   resources:
    #     reservations:
    #       devices:
    #         - driver: nvidia
    #           count: all
    #           capabilities: [gpu]

  redis:
    image: redis:7-alpine
    container_name: giljob-redis
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redis_data:/data
    expose:
      - "6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 10
    networks:
      - internal

  postgres:
    image: postgres:16-alpine
    container_name: giljob-postgres
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./infra/postgres/init.sql:/docker-entrypoint-initdb.d/001-init.sql:ro
    expose:
      - "5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 3s
      retries: 10
    networks:
      - internal

  livekit:
    image: ${LIVEKIT_IMAGE:?pin-livekit-image-version}
    container_name: giljob-livekit
    restart: unless-stopped
    command: ["--config", "/etc/livekit.yaml"]
    volumes:
      - ./infra/livekit.yaml:/etc/livekit.yaml:ro
    ports:
      - "7880:7880/tcp"
      - "7881:7881/tcp"
      - "${LIVEKIT_RTC_UDP_PORT_START:-50000}-${LIVEKIT_RTC_UDP_PORT_END:-50100}:${LIVEKIT_RTC_UDP_PORT_START:-50000}-${LIVEKIT_RTC_UDP_PORT_END:-50100}/udp"
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:7880/ >/dev/null 2>&1 || exit 1"]
      interval: 10s
      timeout: 3s
      retries: 10
    networks:
      - internal
      - public

  coturn:
    image: ${COTURN_IMAGE:?pin-coturn-image-version}
    container_name: giljob-coturn
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./infra/turnserver.conf:/etc/coturn/turnserver.conf:ro
    command: ["-c", "/etc/coturn/turnserver.conf"]
    healthcheck:
      test: ["CMD-SHELL", "turnutils_uclient -u ${TURN_USERNAME} -w ${TURN_PASSWORD} 127.0.0.1 >/dev/null 2>&1 || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5

networks:
  public:
  internal:
    internal: false

volumes:
  caddy_data:
  caddy_config:
  postgres_data:
  redis_data:
```

주의:

- `network_mode: host`는 coturn에서 자주 필요하다. Docker bridge 뒤에서 TURN 포트 매핑이 복잡해질 수 있기 때문이다.
- `internal: false`로 둔 이유는 컨테이너들이 외부 API(SpatialReal/LLM/STT/TTS)에 outbound 접근해야 하기 때문이다. 외부 inbound는 expose/ports로 통제한다.

---

## 7. Reverse proxy 명세

## 7.1 Caddyfile 예시

```caddyfile
{
  email {$TLS_EMAIL}
}

{$PUBLIC_DOMAIN} {
  encode zstd gzip

  header {
    X-Content-Type-Options "nosniff"
    X-Frame-Options "DENY"
    Referrer-Policy "strict-origin-when-cross-origin"
    Permissions-Policy "camera=(self), microphone=(self), fullscreen=(self)"
  }

  # Public ingress must never forward internal engine/control endpoints.
  # Internal callers use http://api:8000 directly over the Docker network with
  # X-GilJob-Internal-Token/HMAC auth. External callers get 404.
  @internal_api path /api/internal/*
  respond @internal_api 404

  @api path /api/*
  reverse_proxy @api api:8000

  @health path /healthz /readyz
  reverse_proxy @health api:8000

  # Optional: LiveKit through same domain path is tricky.
  # Prefer subdomain livekit.example.com for LiveKit websocket.

  reverse_proxy frontend:80
}

{$LIVEKIT_DOMAIN} {
  encode zstd gzip
  reverse_proxy livekit:7880
}
```

권장 domain:

```txt
giljob.example.com       → frontend + API
livekit.example.com      → LiveKit websocket/API
turn.example.com         → coturn realm, DNS only
```

## 7.2 public routing rules

| Public route | Target | Auth | Notes |
|---|---|---|---|
| `/` | frontend | no/session based | static app |
| `/api/sessions` | api | optional login or demo token | creates session |
| `/api/sessions/:id` | api | session owner token | status |
| `/api/sessions/:id/report` | api | report access token | report |
| `/api/admin/*` | api | disabled by default | dev only, IP allowlist |
| `livekit.example.com` | livekit | LiveKit token | WSS |
| TURN ports | coturn | turn credentials | WebRTC fallback |

금지:

```txt
/api/internal/* public open      # Caddy에서 404, API에서도 internal auth 필수
/engine/* public open            # ai-engine은 Docker internal only
/agent1/* public open            # agent1은 Docker internal only
postgres direct
redis direct
```

Internal API 호출 규칙:

- `ai-engine`은 외부 domain이 아니라 `http://api:8000/api/internal/...`로 호출한다.
- 모든 internal request는 `X-GilJob-Internal-Token: <INTERNAL_API_SECRET>` 또는 HMAC signature를 포함한다.
- API 서버는 Docker network 내부 호출이어도 internal token을 검증한다.
- 외부에서 `/api/internal/*`를 호출하면 reverse proxy에서 404, API 직접 접근이 생겨도 401/403이어야 한다.

---

## 8. 환경변수 명세

## 8.1 .env.example

```bash
# Public domains
PUBLIC_DOMAIN=giljob.example.com
LIVEKIT_DOMAIN=livekit.example.com
TURN_DOMAIN=turn.example.com
TLS_EMAIL=you@example.com

# Frontend build-time public vars only
PUBLIC_API_BASE_URL=https://giljob.example.com/api
PUBLIC_LIVEKIT_URL=wss://livekit.example.com

# Postgres
POSTGRES_USER=giljob
POSTGRES_PASSWORD=change-me-strong-password
POSTGRES_DB=giljob
DATABASE_URL=postgresql://giljob:${POSTGRES_PASSWORD}@postgres:5432/giljob

# Redis
REDIS_URL=redis://redis:6379/0
REDIS_STREAM_MAXLEN_PER_SESSION=2000
REDIS_EVENT_DEDUPE_TTL_SECONDS=86400

# Container image pins — never use latest in demo/prod
LIVEKIT_IMAGE=livekit/livekit-server:v1.9.0
COTURN_IMAGE=coturn/coturn:4.6.3-alpine

# LiveKit
LIVEKIT_URL=wss://livekit.example.com
LIVEKIT_INTERNAL_URL=ws://livekit:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=change-me-livekit-secret
LIVEKIT_RTC_UDP_PORT_START=50000
LIVEKIT_RTC_UDP_PORT_END=50100

# TURN
TURN_REALM=turn.example.com
TURN_USERNAME=giljob-turn
TURN_PASSWORD=change-me-turn-password
TURN_SECRET=change-me-turn-shared-secret
TURN_RELAY_PORT_START=49160
TURN_RELAY_PORT_END=49200

# API auth/session
SESSION_SIGNING_SECRET=change-me-session-signing-secret
REPORT_SIGNING_SECRET=change-me-report-signing-secret
DEMO_ACCESS_CODE=change-me-demo-code
SESSION_TOKEN_TTL_SECONDS=7200
REPORT_TOKEN_TTL_SECONDS=2592000
INTERNAL_API_SECRET=change-me-internal-api-secret
INTERNAL_API_AUTH_MODE=shared-secret

# AI Engine
ENGINE_WORKER_ID=engine-01
ENGINE_INTERNAL_BASE_URL=http://ai-engine:8100
AGENT1_BASE_URL=http://agent1:8010
ENGINE_MAX_CONCURRENT_SESSIONS=2
ENGINE_SESSION_IDLE_TIMEOUT_SECONDS=300

# Agent1
AGENT1_PROVIDER=fake
# AGENT1_PROVIDER=gemma-vllm | legacy-cloud-provider | fake | replay
AGENT1_NONVERBAL_WINDOW_SECONDS=3
AGENT1_EVALUATION_WINDOW_SECONDS=16
AGENT1_EVALUATION_TIMEOUT_SECONDS=12

# Agent2
AGENT2_PROVIDER=legacy-cloud-provider
AGENT2_MODEL=legacy-configured-model
AGENT2_API_KEY=change-me-if-cloud-provider
AGENT2_TIMEOUT_SECONDS=5

# STT
STT_PROVIDER=fake
# STT_PROVIDER=local-whisper | cloud | fake
STT_LANGUAGE=ko
STT_TIMEOUT_SECONDS=3

# TTS
TTS_PROVIDER=fake
# TTS_PROVIDER=edge | openai | elevenlabs | local | fake
TTS_SAMPLE_RATE=16000
TTS_CHANNELS=1

# SpatialReal
SPATIALREAL_ENABLED=false
SPATIALREAL_API_KEY=change-me
SPATIALREAL_APP_ID=change-me
SPATIALREAL_AVATAR_ID=change-me
SPATIALREAL_REGION=us-west
SPATIALREAL_CONSOLE_ENDPOINT=https://console.us-west.spatialwalk.cloud/v1/console
SPATIALREAL_INGRESS_ENDPOINT=wss://api.us-west.spatialwalk.cloud/v2/driveningress

# Privacy / retention
RAW_MEDIA_STORAGE_ENABLED=false
DEBUG_ARTIFACT_RETENTION_DAYS=1
REPORT_RETENTION_DAYS=30
TRANSCRIPT_RETENTION_DAYS=30

# Logging
LOG_LEVEL=INFO
JSON_LOGS=true
```

## 8.2 env 원칙

- `.env`는 git commit 금지
- `.env.example`만 commit
- frontend build arg에는 public value만 전달
- `VITE_*`/public env에 secret 넣지 않기
- API/engine/agent1 container만 provider secret 접근 가능

---

## 9. LiveKit self-host 명세

## 9.1 livekit.yaml 예시

```yaml
port: 7880
bind_addresses:
  - "0.0.0.0"

rtc:
  tcp_port: 7881
  port_range_start: 50000
  port_range_end: 50100
  use_external_ip: true

keys:
  devkey: change-me-livekit-secret

turn:
  enabled: false
  # MVP에서는 coturn 별도 컨테이너 권장

logging:
  level: info
```

## 9.2 LiveKit token 발급

API 서버가 participant token을 발급한다.

participant identities:

```txt
candidate_{session_id}
engine_{session_id}
avatar_{session_id}
```

room name:

```txt
giljob_{session_id}
```

candidate 권한:

```txt
roomJoin: true
canPublish: true
canSubscribe: true
canPublishData: true
```

engine 권한:

```txt
roomJoin: true
canPublish: true
canSubscribe: true
canPublishData: true
hidden: true, 가능하면
```

avatar 권한:

```txt
roomJoin: true
canPublish: true
canSubscribe: false 또는 필요시 true
```

## 9.3 LiveKit 네트워크 체크

배포 후 반드시 확인:

```bash
docker compose logs livekit
curl -f http://localhost:7880/
```

브라우저에서 확인:

- WebSocket 연결 성공
- candidate audio/video publish 성공
- engine subscribe 성공
- 외부 네트워크에서 접속 가능
- 모바일 핫스팟/다른 Wi-Fi에서도 연결 가능

---

## 10. coturn 명세

## 10.1 turnserver.conf 예시

```conf
listening-port=3478
tls-listening-port=5349
fingerprint
lt-cred-mech
realm=turn.example.com
server-name=turn.example.com
user=giljob-turn:change-me-turn-password

# For demo, no-cli can reduce attack surface
no-cli

# Logging
simple-log
log-file=stdout

# Relay ports — must match TURN_RELAY_PORT_START/END and firewall/security group
min-port=49160
max-port=49200

# Security hardening
no-multicast-peers
no-loopback-peers

# If behind public IP, set external-ip
# external-ip=PUBLIC_IP
```

## 10.2 TURN credentials 정책

MVP는 static credential도 가능하지만, 가능하면 API가 ephemeral TURN credential을 발급한다.

초기 MVP:

```txt
static TURN username/password
```

v1:

```txt
HMAC time-limited TURN credentials
```

---

## 11. API 서버 명세

## 11.1 책임

API 서버는 system control plane의 중심이다.

책임:

- 세션 생성
- LiveKit room/token 발급
- session state owner
- state transition CAS 검증
- report 조회
- demo auth/access code 검증
- engine heartbeat 수신
- health aggregate

하지 않는 것:

- raw media 직접 처리
- Agent1 분석 직접 실행
- long-running STT/LLM loop 직접 실행

## 11.2 API endpoint 목록

```http
GET  /healthz
GET  /readyz
POST /api/sessions
GET  /api/sessions/{session_id}
POST /api/sessions/{session_id}/end
GET  /api/sessions/{session_id}/report
POST /api/sessions/{session_id}/events
POST /api/internal/engine/heartbeat
POST /api/internal/sessions/{session_id}/state-transition
```

## 11.3 POST /api/sessions

Request:

```json
{
  "access_code": "demo-code",
  "candidate_profile": {
    "display_name": "지원자",
    "target_role": "backend_engineer",
    "experience_level": "junior",
    "language": "ko"
  },
  "options": {
    "max_duration_min": 20,
    "debug_signals": true,
    "raw_media_consent": false,
    "agent1_enabled": true,
    "avatar_enabled": true
  }
}
```

Response:

```json
{
  "session_id": "sess_01J...",
  "room_name": "giljob_sess_01J...",
  "session_auth": {
    "token_type": "opaque_bearer",
    "access_token": "sess_tok_256bit_random_base64url",
    "scope": ["session:read", "session:end", "events:write"],
    "expires_at": "2026-05-30T05:00:00Z"
  },
  "report_auth": {
    "status": "not_issued_until_report_ready"
  },
  "livekit": {
    "url": "wss://livekit.example.com",
    "candidate_token": "jwt...",
    "expires_at": "2026-05-30T04:00:00Z"
  },
  "state": "WAITING_FRONTEND",
  "frontend": {
    "events_mode": "livekit_data_channel_and_polling",
    "status_url": "/api/sessions/sess_01J..."
  }
}
```

Initial state rule:

```txt
POST /api/sessions의 성공 응답 state는 항상 WAITING_FRONTEND다.

Canonical flow:
1. API opens a single DB transaction.
2. API inserts session row as CREATED with state_version=0, or keeps CREATED only as an internal transaction-local phase.
3. API generates session_auth.access_token and livekit.candidate_token.
4. API stores session_token_hash and expiry.
5. Before commit/response, API records the CREATED → WAITING_FRONTEND transition with event_id=session.initialized and increments state_version to 1.
6. API commits and returns state=WAITING_FRONTEND.

If token issuance fails before step 5, the transaction rolls back or records CREATED → FAILED_TOKEN_ISSUE. Clients must never rely on observing CREATED from a successful POST response.
```

## 11.3.1 Token contract

MVP token은 JWT가 아니라 **opaque bearer token**을 기본으로 한다. 브라우저는 token 값을 알지만, 서버는 원문을 저장하지 않고 hash만 저장한다.

| Token | 발급 시점 | 전달 위치 | Scope | TTL | 저장 방식 |
|---|---|---|---|---:|---|
| `session_auth.access_token` | `POST /api/sessions` | response body | `session:read`, `session:end`, `events:write` | 기본 2h / `SESSION_TOKEN_TTL_SECONDS=7200` | `sessions.session_token_hash` |
| `livekit.candidate_token` | `POST /api/sessions` | response body | LiveKit room join/publish/subscribe | 기본 30m | 저장하지 않음, LiveKit JWT |
| `report_auth.access_token` | report 생성 완료 시 | `GET /api/sessions/{id}` 또는 end 이후 status | `report:read` | 기본 30d / `REPORT_TOKEN_TTL_SECONDS=2592000` | `reports.access_token_hash` |
| internal token | 배포 시 `.env` | `X-GilJob-Internal-Token` header | internal only | rotate manually | env only |

Canonical TTL source:

```txt
SESSION_TOKEN_TTL_SECONDS=7200      # 2h
REPORT_TOKEN_TTL_SECONDS=2592000    # 30d
```

`.env.example`, runtime config, token table이 다르면 preflight가 실패해야 한다. 운영에서 TTL을 바꾸려면 세 위치를 같은 값으로 바꾸고 문서 버전을 올린다.

Hash 규칙:

```txt
session_token_hash = base64url(HMAC-SHA256(SESSION_SIGNING_SECRET, session_token_plaintext))
report_token_hash  = base64url(HMAC-SHA256(REPORT_SIGNING_SECRET,  report_token_plaintext))
```

`SESSION_SIGNING_SECRET`와 `REPORT_SIGNING_SECRET`는 서로 다른 값이어야 한다. Report token 검증은 `reports.access_token_hash`와 `REPORT_SIGNING_SECRET`를 사용하고, session token 검증은 `sessions.session_token_hash`와 `SESSION_SIGNING_SECRET`를 사용한다.

Report token 발급 흐름:

1. 세션이 `REPORT_GENERATING → ENDED`로 전이된다.
2. API/report generator가 `report_auth.access_token`을 새로 생성한다.
3. token hash는 `reports.access_token_hash`에 저장한다.
4. `GET /api/sessions/{id}/report`는 report access token을 담은 Authorization bearer header를 요구한다. session token도 owner scope가 유효하면 허용 가능하지만 report token이 우선이다.
5. report token은 URL query에 장기 노출하지 않는다. 필요하면 최초 조회 후 fragment/history replace로 제거한다.

## 11.4 GET /api/sessions/{id}

Headers:

```http
Authorization: Bearer <session-token>
```

Response:

```json
{
  "session_id": "sess_01J...",
  "state": "CANDIDATE_ANSWERING",
  "state_version": 12,
  "room_name": "giljob_sess_01J...",
  "participants": {
    "candidate_joined": true,
    "engine_joined": true,
    "avatar_joined": true
  },
  "current_turn": {
    "turn_id": "turn_0003",
    "speaker": "candidate",
    "started_at": "2026-05-30T03:10:00Z"
  },
  "latest_transcript": "저는 FastAPI 기반 백엔드를...",
  "latest_agent_status": {
    "stt": "ok",
    "agent1": "ok",
    "agent2": "idle",
    "avatar": "ok"
  }
}
```

## 11.5 POST /api/sessions/{id}/end

Request:

```json
{
  "reason": "candidate_clicked_end"
}
```

Response:

```json
{
  "session_id": "sess_01J...",
  "state": "REPORT_GENERATING",
  "report_url": null,
  "report_auth": {
    "status": "pending"
  }
}
```

Report가 준비된 뒤 `GET /api/sessions/{id}`는 다음을 포함할 수 있다.

```json
{
  "report_ready": true,
  "report_url": "/api/sessions/sess_01J.../report",
  "report_auth": {
    "token_type": "opaque_bearer",
    "access_token": "rpt_tok_256bit_random_base64url",
    "scope": ["report:read"],
    "expires_at": "2026-06-29T03:10:00Z"
  }
}
```

## 11.6 State transition API

Internal only. Public reverse proxy must block this route. Engine calls it through `http://api:8000` on the Docker network.

```http
POST /api/internal/sessions/{session_id}/state-transition
X-GilJob-Internal-Token: ${INTERNAL_API_SECRET}
```

Request:

```json
{
  "actor": "ai-engine",
  "expected_version": 12,
  "from_state": "ANALYZING",
  "to_state": "DECIDING_NEXT",
  "event_id": "evt_01J...",
  "reason": "stt_final_and_agent1_timeout_or_ready",
  "metadata": {
    "turn_id": "turn_0003"
  }
}
```

Response success:

```json
{
  "ok": true,
  "session_id": "sess_01J...",
  "state": "DECIDING_NEXT",
  "state_version": 13
}
```

Response conflict:

```json
{
  "ok": false,
  "error": "state_version_conflict",
  "current_state": "AVATAR_SPEAKING",
  "current_version": 14
}
```

---

## 12. SessionCoordinator 명세

Reviewer 지적을 반영해, API 서버가 state owner다.

## 12.1 State ownership

| State | Owner | Notes |
|---|---|---|
| CREATED | API | transaction-local/transient. 성공한 `POST /api/sessions` 응답에서는 외부에 노출하지 않음 |
| WAITING_FRONTEND | API | session token + candidate LiveKit token 발급 및 hash 저장 완료. 성공한 `POST /api/sessions`의 canonical response state |
| WAITING_ENGINE | API/Engine | frontend/candidate 준비 후 engine attach 대기 |
| READY | API | candidate+engine 준비 |
| AVATAR_SPEAKING | Engine requests, API confirms | avatar event 기반 |
| CANDIDATE_ANSWERING | Engine requests, API confirms | VAD/STT/data event |
| ANALYZING | Engine requests, API confirms | turn end |
| DECIDING_NEXT | Engine requests, API confirms | Agent2 started |
| REPORT_GENERATING | Engine/API | session end |
| ENDED | API | final state |
| FAILED_TOKEN_ISSUE | API | token 발급/hash 저장 실패 |
| FAILED_LIVEKIT_JOIN | API/Engine | LiveKit room/token/join 실패 |
| FAILED_ENGINE_ATTACH | API/Engine | engine attach/heartbeat 실패 |
| FAILED_AGENT_PIPELINE | Engine/API | STT/Agent1/Agent2/avatar pipeline fatal 실패 |
| FAILED_REPORT | API/Engine | report 생성 실패 |
| FAILED_INTERNAL | API | 분류되지 않은 내부 오류 |

## 12.1.1 Session creation state algorithm

성공한 `POST /api/sessions`에서 client가 관찰하는 최초 state는 `WAITING_FRONTEND`로 고정한다.

```txt
DB insert:        CREATED, state_version=0
Token issue:      session_auth + livekit.candidate_token 생성
Hash persist:     sessions.session_token_hash 저장
Audit transition: CREATED → WAITING_FRONTEND, event_id=session.initialized, resulting_version=1
Response:         state=WAITING_FRONTEND, state_version=1
```

`CREATED`는 session 생성 transaction 내부와 transition audit에서만 의미가 있다. Frontend/Engine은 `CREATED` polling 분기를 구현하지 않는다.

## 12.2 State transition 불변조건

- 모든 state transition은 `state_version`을 증가시킨다.
- Engine은 `expected_version`을 포함해야 한다.
- API는 현재 version과 다르면 reject한다.
- 모든 transition은 `event_id`로 idempotent해야 한다.
- 중복 `event_id`는 같은 response를 반환한다.
- 오래된 event는 drop한다.

## 12.3 허용 transition

```txt
CREATED → WAITING_FRONTEND
WAITING_FRONTEND → WAITING_ENGINE
WAITING_ENGINE → READY
READY → AVATAR_SPEAKING
AVATAR_SPEAKING → CANDIDATE_ANSWERING
AVATAR_SPEAKING → READY              # avatar opening failed fallback
CANDIDATE_ANSWERING → ANALYZING
ANALYZING → DECIDING_NEXT
DECIDING_NEXT → AVATAR_SPEAKING
DECIDING_NEXT → CANDIDATE_ANSWERING  # text-only fallback / skipped avatar
ANY_ACTIVE → REPORT_GENERATING   # DB seed에서는 concrete active states로 확장
REPORT_GENERATING → ENDED
ANY_ACTIVE → FAILED_*            # DB seed에서는 active states × concrete failure states로 확장
FAILED_* → ENDED                 # DB seed에서는 concrete failure states로 확장
```

## 12.4 금지 transition 예시

```txt
CANDIDATE_ANSWERING → AVATAR_SPEAKING 직접 금지
AVATAR_SPEAKING → DECIDING_NEXT 직접 금지
ENDED → any 금지
FAILED_* → active state 금지, manual recovery 제외
```

## 12.5 Atomic CAS transition algorithm

State transition은 반드시 단일 DB transaction에서 처리한다. 애플리케이션 메모리에서 현재 state를 읽고 나중에 update하는 방식은 금지한다.

Pseudo-SQL:

```sql
BEGIN;

-- 1. idempotency: 이미 처리된 event_id면 기존 결과를 반환하고 종료
SELECT resulting_version, to_state
FROM state_transitions
WHERE event_id = :event_id;

-- 2. allowed transition 검증
SELECT 1
FROM allowed_state_transitions
WHERE from_state = :from_state
  AND to_state = :to_state
  AND enabled = true;

-- 3. CAS update: state와 version이 둘 다 맞을 때만 update
UPDATE sessions
SET state = :to_state,
    state_version = state_version + 1,
    updated_at = now()
WHERE id = :session_id
  AND state = :from_state
  AND state_version = :expected_version
RETURNING state_version;

-- 4. UPDATE rowcount = 0이면 conflict. insert 금지, rollback.

-- 5. transition audit insert
INSERT INTO state_transitions (
  session_id, event_id, actor, from_state, to_state,
  expected_version, resulting_version, reason, metadata
) VALUES (...);

COMMIT;
```

Conflict response는 현재 state/version을 다시 조회해 반환한다. Engine은 conflict를 받으면 local state를 버리고 API state를 재동기화한다.

## 12.6 Allowed transition table

Allowed transition은 코드 enum만이 아니라 DB seed data 또는 migration으로도 고정한다.

```sql
CREATE TABLE allowed_state_transitions (
  from_state TEXT NOT NULL,
  to_state TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT true,
  description TEXT,
  PRIMARY KEY (from_state, to_state)
);
```

`ANY_ACTIVE` 같은 문서용 표현은 실제 DB에는 넣지 않는다. migration에서 active state 목록을 펼쳐서 insert한다.


---

## 13. 공통 이벤트 Envelope

모든 내부 이벤트는 공통 envelope을 가진다.

```json
{
  "schema": "giljob.event.envelope.v1",
  "message_id": "msg_01J...",
  "event_type": "stt.final",
  "schema_version": "v1",
  "session_id": "sess_01J...",
  "turn_id": "turn_0003",
  "seq": 42,
  "trace_id": "trace_01J...",
  "causation_id": "msg_01J_previous",
  "correlation_id": "sess_01J...",
  "producer": "ai-engine",
  "created_at_ms": 1780123456789,
  "payload": {}
}
```

필드 규칙:

- `message_id`: globally unique
- `seq`: session-local monotonic sequence
- `trace_id`: 한 세션/요청 흐름 추적
- `causation_id`: 어떤 event 때문에 생긴 event인지
- `correlation_id`: 보통 session_id
- `producer`: `frontend`, `api`, `ai-engine`, `agent1`, `stt`, `agent2`, `avatar`

Redis stream key:

```txt
giljob:session:{session_id}:events
```

Redis pubsub channel:

```txt
giljob.session.{session_id}.events
```

---

## 14. Redis runtime protocol

## 14.1 Redis 사용 목적

- session event stream
- engine work queue
- latest status cache
- frontend polling cache
- backpressure buffer

## 14.2 Key design

```txt
giljob:session:{sid}:events              Redis Stream
giljob:session:{sid}:status              Hash or JSON
giljob:session:{sid}:turn:{tid}:signals  List/JSON
giljob:engine:heartbeat:{worker_id}      String/Hash TTL
giljob:queue:engine                      Stream/List
giljob:dedupe:{message_id}               String TTL
```

## 14.3 Queue policy

우선순위:

1. `stt.final`
2. `turn.ended`
3. `agent2.output`
4. `avatar.interrupt`
5. `stt.partial`
6. `agent1.nonverbal`
7. `agent1.evaluation`
8. debug events

Drop policy:

- STT partial: keep latest per turn
- Nonverbal: drop oldest if queue full
- Evaluation: keep completed, but do not block Agent2
- Agent2 output: never drop
- Final transcript: never drop


## 14.4 Queue capacity / TTL / retry policy

| Event class | Redis structure | Max length / TTL | Drop policy | Retry | DLQ |
|---|---|---:|---|---:|---|
| session event stream | Stream `giljob:session:{sid}:events` | `MAXLEN ~ 2000`, TTL 24h after ENDED | never drop final/audit events; trim approximate old debug events | n/a | no |
| STT partial | Hash `latest_stt_partial:{sid}:{turn}` + stream summary | keep latest only, TTL 10m | overwrite older partial | 0 | no |
| STT final | Stream + DB | never trim before DB write | never drop | 3 | yes |
| Agent1 nonverbal | Stream + optional DB | max 60 per turn | drop oldest below confidence 0.5 first | 1 | no |
| Agent1 evaluation | Stream + DB when complete | max 10 per turn | late result becomes report-only | 1 | yes if provider error |
| Agent2 output | DB + stream | never drop | retry once, then fallback | 1 | yes |
| avatar events | stream | max 100 per session | drop old `avatar.progress`, keep start/end/interrupt | 1 | no |

Redis write examples:

```txt
XADD giljob:session:{sid}:events MAXLEN ~ 2000 * message_id ... event_type ...
SETEX giljob:dedupe:{message_id} 86400 1
HSET giljob:session:{sid}:status state CANDIDATE_ANSWERING state_version 12
```

Fallback triggers:

- session event backlog > 1000: stop emitting debug events.
- Agent1 queue wait > 2s for nonverbal: emit `unknown` signal.
- Agent1 evaluation wait > 12s: mark late/report-only.
- Agent2 queue wait > 5s: deterministic fallback question.

---

## 15. Database schema

Postgres를 기본으로 한다.

## 15.1 sessions

```sql
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  room_name TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL,
  state_version INTEGER NOT NULL DEFAULT 0,

  -- Generated by API at session creation. engine_identity is reserved early even
  -- if the engine has not joined yet, so NOT NULL remains valid.
  candidate_identity TEXT NOT NULL,
  engine_identity TEXT NOT NULL,
  avatar_identity TEXT,

  session_token_hash TEXT NOT NULL,
  session_token_expires_at TIMESTAMPTZ NOT NULL,

  candidate_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
  options JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ,
  failure_reason TEXT,
  report_ready BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX idx_sessions_state ON sessions(state);
CREATE INDEX idx_sessions_created_at ON sessions(created_at);
CREATE INDEX idx_sessions_token_hash ON sessions(session_token_hash);
```

Identity 생성 규칙:

```txt
candidate_identity = candidate_{session_id}
engine_identity    = engine_{session_id}
avatar_identity    = avatar_{session_id} or null when avatar disabled
```

API가 session 생성 시 세 identity를 예약하므로 DB에는 더미/unknown identity를 넣지 않는다. Engine attach 여부는 `participants.engine_joined`/heartbeat/status로 표현한다.

## 15.2 state_transitions

```sql
CREATE TABLE state_transitions (
  id BIGSERIAL PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  event_id TEXT NOT NULL UNIQUE,
  actor TEXT NOT NULL,
  from_state TEXT NOT NULL,
  to_state TEXT NOT NULL,
  expected_version INTEGER NOT NULL,
  resulting_version INTEGER NOT NULL,
  reason TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Allowed transition seed table:

```sql
CREATE TABLE allowed_state_transitions (
  from_state TEXT NOT NULL,
  to_state TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT true,
  description TEXT,
  PRIMARY KEY (from_state, to_state)
);

-- Full seed rows. Do not insert wildcard names such as ANY_ACTIVE or FAILED_*.
-- The CTEs below expand the documented wildcard transitions into concrete DB rows.
WITH
base_transitions(from_state, to_state, description) AS (
  VALUES
    ('CREATED', 'WAITING_FRONTEND', 'session initialized; session/livekit tokens issued'),
    ('CREATED', 'FAILED_TOKEN_ISSUE', 'session token or candidate token issuance failed'),
    ('WAITING_FRONTEND', 'WAITING_ENGINE', 'candidate ready, engine pending'),
    ('WAITING_ENGINE', 'READY', 'candidate and engine ready'),
    ('READY', 'AVATAR_SPEAKING', 'opening or follow-up question'),
    ('AVATAR_SPEAKING', 'CANDIDATE_ANSWERING', 'candidate starts speaking or interrupts avatar'),
    ('AVATAR_SPEAKING', 'READY', 'avatar opening/follow-up failed; return to ready fallback'),
    ('CANDIDATE_ANSWERING', 'ANALYZING', 'turn ended'),
    ('ANALYZING', 'DECIDING_NEXT', 'STT final and Agent1 analysis ready/timeout'),
    ('DECIDING_NEXT', 'AVATAR_SPEAKING', 'Agent2 output ready for avatar/TTS playback'),
    ('DECIDING_NEXT', 'CANDIDATE_ANSWERING', 'text-only fallback or skipped avatar'),
    ('REPORT_GENERATING', 'ENDED', 'report ready'),
    ('REPORT_GENERATING', 'FAILED_REPORT', 'report generation failed')
),
active_states(state) AS (
  VALUES
    ('WAITING_FRONTEND'),
    ('WAITING_ENGINE'),
    ('READY'),
    ('AVATAR_SPEAKING'),
    ('CANDIDATE_ANSWERING'),
    ('ANALYZING'),
    ('DECIDING_NEXT')
),
failure_states(state) AS (
  VALUES
    ('FAILED_TOKEN_ISSUE'),
    ('FAILED_LIVEKIT_JOIN'),
    ('FAILED_ENGINE_ATTACH'),
    ('FAILED_AGENT_PIPELINE'),
    ('FAILED_REPORT'),
    ('FAILED_INTERNAL')
),
report_transitions(from_state, to_state, description) AS (
  SELECT state, 'REPORT_GENERATING', 'session end requested while active'
  FROM active_states
),
failure_transitions(from_state, to_state, description) AS (
  SELECT a.state, f.state, 'fatal failure while active'
  FROM active_states a CROSS JOIN failure_states f
),
failure_end_transitions(from_state, to_state, description) AS (
  SELECT state, 'ENDED', 'failure acknowledged and session closed'
  FROM failure_states
)
INSERT INTO allowed_state_transitions (from_state, to_state, description)
SELECT * FROM base_transitions
UNION ALL SELECT * FROM report_transitions
UNION ALL SELECT * FROM failure_transitions
UNION ALL SELECT * FROM failure_end_transitions
ON CONFLICT (from_state, to_state) DO UPDATE
SET description = EXCLUDED.description,
    enabled = true;
```

## 15.3 turns

```sql
CREATE TABLE turns (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  turn_index INTEGER NOT NULL,
  speaker TEXT NOT NULL,
  question_text TEXT,
  transcript_final TEXT,
  started_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ,
  duration_ms INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(session_id, turn_index)
);
```

## 15.4 transcripts

```sql
CREATE TABLE transcripts (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  turn_id TEXT REFERENCES turns(id),
  speaker TEXT NOT NULL,
  is_final BOOLEAN NOT NULL,
  text TEXT NOT NULL,
  language TEXT,
  confidence REAL,
  start_ms INTEGER,
  end_ms INTEGER,
  provider TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_transcripts_session_turn ON transcripts(session_id, turn_id);
```

## 15.5 agent1_signals

```sql
CREATE TABLE agent1_signals (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  turn_id TEXT REFERENCES turns(id),
  signal_type TEXT NOT NULL,
  window_start_ms INTEGER,
  window_end_ms INTEGER,
  confidence REAL,
  latency_ms INTEGER,
  provider TEXT,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_agent1_session_turn ON agent1_signals(session_id, turn_id);
CREATE INDEX idx_agent1_signal_type ON agent1_signals(signal_type);
```

## 15.6 agent2_outputs

```sql
CREATE TABLE agent2_outputs (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  turn_id TEXT REFERENCES turns(id),
  action TEXT NOT NULL,
  speak_text TEXT NOT NULL,
  model TEXT,
  latency_ms INTEGER,
  input_json JSONB NOT NULL,
  output_json JSONB NOT NULL,
  validation_status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 15.7 reports

```sql
CREATE TABLE reports (
  session_id TEXT PRIMARY KEY REFERENCES sessions(id),
  report_json JSONB NOT NULL,
  report_markdown TEXT NOT NULL,
  access_token_hash TEXT NOT NULL,
  token_issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_reports_access_token_hash ON reports(access_token_hash);
```

## 15.8 consent_records

```sql
CREATE TABLE consent_records (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  consent_type TEXT NOT NULL,
  granted BOOLEAN NOT NULL,
  granted_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
```

---

## 16. AI Engine 명세

## 16.1 책임

AI Engine은 실시간 면접 loop의 orchestrator다.

책임:

- API 서버에서 생성된 session 감지
- LiveKit room에 engine participant로 join
- candidate audio/video track subscribe
- media fanout
- STT 실행
- Agent1 호출
- Agent2 context build/decision
- TTS 생성
- SpatialReal adapter 실행
- avatar interrupt 처리
- report generation trigger

## 16.2 내부 모듈 구조

```txt
backend/ai-engine/src/giljob_engine/
  main.py
  config.py
  logging.py

  livekit_client/
    room.py
    participants.py
    tracks.py
    data_channel.py

  session/
    coordinator_client.py
    manager.py
    state_machine.py
    heartbeat.py
    cleanup.py

  media/
    audio_buffer.py
    video_sampler.py
    fanout.py
    vad.py
    timestamps.py

  stt/
    base.py
    fake.py
    local_whisper.py
    cloud.py

  agent1/
    client.py
    schemas.py
    signal_store.py

  agent2/
    context_builder.py
    llm_client.py
    prompts.py
    output_schema.py
    fallback.py

  avatar/
    tts.py
    spatialreal.py
    fallback_text.py
    interrupt.py

  report/
    generator.py
    markdown.py

  api/
    health.py
    debug.py
```

## 16.3 Engine lifecycle

```txt
1. start process
2. load config/env
3. connect postgres/redis
4. register heartbeat
5. watch for sessions needing engine attach
6. for each session:
   a. get engine LiveKit token from API or internal signing
   b. join room
   c. subscribe candidate tracks
   d. start media fanout
   e. run interview loop
   f. generate report
   g. leave room
7. cleanup stale sessions
```

## 16.4 Engine concurrency

MVP default:

```txt
ENGINE_MAX_CONCURRENT_SESSIONS=1 or 2
```

이유:

- STT/Agent1/Agent2/TTS가 동시에 돌면 CPU/GPU contention 발생
- 졸작 데모는 안정성이 우선

동시 세션 초과 시:

```json
{
  "error": "engine_capacity_exceeded",
  "message": "현재 면접 엔진이 바쁩니다. 잠시 후 다시 시도해주세요."
}
```

---

## 17. Media pipeline 명세

## 17.1 Input tracks

Candidate publishes:

```txt
audio: microphone, Opus via WebRTC
video: camera, VP8/H264 via WebRTC
```

Engine receives decoded frames/audio through LiveKit SDK.

Internal normalized format:

```txt
audio: PCM s16le, mono, 16kHz
video: JPEG/RGB frames, 640x480, 1fps sampling for Agent1
```

## 17.2 Fanout

```txt
candidate audio
  ├─ VAD
  ├─ STT
  ├─ interruption detector
  └─ Agent1 audio window assembler

candidate video
  ├─ Agent1 frame sampler
  └─ optional quality monitor
```

## 17.3 Buffer 정책

Audio buffer:

```txt
max duration: 60s per turn
frame chunk: 20ms or provider-native
overflow: keep recent, mark quality warning
```

Video sampler:

```txt
sample rate: 1fps default
max frame width: 640
max frame queue: 40 frames
overflow: drop oldest frames
```

Agent1 evaluation:

```txt
nonverbal window: 3s
evaluation window: 16s
tail flush: optional, not critical path
```

---

## 18. Turn boundary / interruption 명세

## 18.1 Turn start

Candidate turn starts when one of:

- VAD speech start during `READY`
- VAD speech start during `AVATAR_SPEAKING` and interrupt allowed
- frontend sends manual answer start
- STT partial begins with confidence above threshold

Event:

```json
{
  "event_type": "turn.started",
  "payload": {
    "speaker": "candidate",
    "reason": "vad_speech_start",
    "at_ms": 12345
  }
}
```

## 18.2 Turn end

Candidate turn ends when one of:

- VAD silence > 1000ms and STT final available
- user clicks answer done
- max answer duration exceeded
- engine timeout recovery

Event:

```json
{
  "event_type": "turn.ended",
  "payload": {
    "speaker": "candidate",
    "reason": "vad_silence_and_stt_final",
    "duration_ms": 31200
  }
}
```

## 18.3 Avatar interruption FSM

Avatar speaking 중 candidate가 끼어들면:

```txt
AVATAR_SPEAKING
  └─ candidate speech detected
      ├─ if Agent2 output allow_interrupt=true
      │    ├─ send avatar.interrupt
      │    ├─ stop TTS queue
      │    ├─ call SpatialReal interrupt if supported
      │    ├─ mark avatar turn interrupted
      │    └─ transition → CANDIDATE_ANSWERING
      └─ else
           ├─ ignore short noise under threshold
           └─ if sustained speech, transition with forced interrupt
```

Interrupt thresholds:

```txt
speech probability >= 0.7
sustained duration >= 300ms
ignore if avatar speech just started < 500ms and candidate noise < 300ms
force interrupt if sustained speech >= 1200ms
```

Interrupt event:

```json
{
  "event_type": "avatar.interrupted",
  "payload": {
    "reason": "candidate_started_speaking",
    "avatar_turn_id": "turn_0004_avatar",
    "candidate_turn_id": "turn_0005",
    "avatar_audio_elapsed_ms": 3400,
    "allow_interrupt": true
  }
}
```

---

## 19. Agent1 명세

## 19.1 책임

Agent1은 Multi_Modal_Module이다.

입력:

- sampled video frames
- audio PCM chunks
- optional transcript partial/final
- session metadata

출력:

- nonverbal signal
- evaluation signal
- provider status
- media quality signal

Agent1은 질문을 생성하지 않는다.

## 19.2 Agent1 HTTP API

Internal only.

```http
GET /healthz
POST /v1/sessions/{session_id}/start
POST /v1/sessions/{session_id}/window/nonverbal
POST /v1/sessions/{session_id}/window/evaluation
POST /v1/sessions/{session_id}/end
```

## 19.3 Nonverbal request

```json
{
  "session_id": "sess_01J...",
  "turn_id": "turn_0003",
  "window_start_ms": 12000,
  "window_end_ms": 15000,
  "frames": [
    {
      "t_ms": 12000,
      "mime": "image/jpeg",
      "data_base64": "..."
    }
  ],
  "audio": {
    "mime": "audio/pcm;rate=16000;channels=1;format=s16le",
    "data_base64": "..."
  },
  "transcript_hint": "저는 이전 프로젝트에서"
}
```

## 19.4 Nonverbal response

```json
{
  "schema": "giljob.agent1.nonverbal.v1",
  "signal_id": "sig_nv_01J...",
  "session_id": "sess_01J...",
  "turn_id": "turn_0003",
  "window_start_ms": 12000,
  "window_end_ms": 15000,
  "state": "hesitant",
  "intensity": 0.67,
  "confidence": 0.72,
  "evidence": [
    "시선이 아래로 자주 이동",
    "말끝이 약하게 끊김"
  ],
  "suggested_policy": "supportive_followup",
  "latency_ms": 640,
  "provider": "fake-or-gemma-vllm",
  "created_at_ms": 1780123456789
}
```

## 19.5 Evaluation response

```json
{
  "schema": "giljob.agent1.evaluation.v1",
  "signal_id": "sig_eval_01J...",
  "session_id": "sess_01J...",
  "turn_id": "turn_0003",
  "window_start_ms": 16000,
  "window_end_ms": 32000,
  "verbal": {
    "logic": "원인-결과 설명은 있으나 근거 수치가 부족함",
    "structure": "결론 이후 배경 설명으로 흐름이 다소 역전됨",
    "specificity": "본인 기여가 추상적임"
  },
  "vocal": {
    "volume": "일정함",
    "pace": "후반부 빠름",
    "pauses": "핵심 용어 앞에서 멈춤 2회",
    "intonation": "문장 끝 확신이 약함"
  },
  "visual": {
    "eye_contact": "중앙 유지 비율 낮음",
    "posture": "안정적",
    "expression": "긴장한 미소",
    "gesture_over_time": "손 제스처 거의 없음"
  },
  "critique": [
    "성과를 수치화하면 설득력이 올라감"
  ],
  "key_observations": [
    "답변 후반에 말 속도가 빨라짐"
  ],
  "suggested_policy": "ask_for_specific_metrics",
  "confidence": 0.7,
  "latency_ms": 6200,
  "provider": "fake-or-gemma-vllm",
  "created_at_ms": 1780123456789
}
```

## 19.6 Agent1 timeout 정책

```txt
nonverbal soft timeout: 1.5s
nonverbal hard timeout: 2.0s
evaluation soft timeout: 8s
evaluation hard timeout: 12s
```

- nonverbal timeout: `unknown` signal 생성
- evaluation timeout: 해당 window skip, late result는 report-only
- 3회 연속 실패: `DEGRADED_AGENT1`

---

## 20. STT 명세

## 20.1 STT event

```json
{
  "event_type": "stt.final",
  "payload": {
    "schema": "giljob.stt.transcript.v1",
    "session_id": "sess_01J...",
    "turn_id": "turn_0003",
    "speaker": "candidate",
    "is_final": true,
    "text": "저는 FastAPI 기반 백엔드를 맡았고...",
    "language": "ko",
    "confidence": 0.93,
    "start_ms": 12000,
    "end_ms": 42100,
    "provider": "fake-or-local-whisper"
  }
}
```

## 20.2 STT fallback

- STT provider 실패 시 candidate에게 “다시 말씀해달라” 요청
- dev/demo mode에서는 typed answer fallback 허용
- 2회 연속 실패 시 `FAILED_STT` 대신 `DEGRADED_STT_TEXT_INPUT`로 전환 가능

---

## 21. Agent2 명세

## 21.1 책임

Agent2는 면접관 brain이다.

입력:

- 현재 면접 단계
- 이전 질문/답변 history
- current final transcript
- Agent1 signals
- STT confidence
- time budget

출력:

- 다음 질문 또는 피드백
- avatar speak text
- UI state
- report memory
- rubric update

## 21.2 ContextBuilder 규칙

Agent2에 raw signal 전체를 넣지 않는다. ContextBuilder가 압축한다.

선택 규칙:

```txt
recent_nonverbal: 최근 2~3개, confidence >= 0.5 우선
evaluation_summary: 완료된 windows만 요약
late_tail: 사용하지 않음, 다음 턴/report로 넘김
stt_confidence < 0.75: clarification 우선
agent1_confidence < 0.5: multimodal 반영 약화
```

## 21.3 Agent2 output schema

```json
{
  "schema": "giljob.agent2.output.v1",
  "decision": {
    "action": "ask_followup",
    "question_type": "specific_metrics",
    "reason_summary": "역할은 설명했지만 성과 지표와 본인 기여가 불명확함"
  },
  "avatar": {
    "speak_text": "좋아요. 그럼 그 프로젝트에서 본인이 직접 개선한 지표나 수치가 있었나요?",
    "tone": "supportive_but_precise",
    "gesture_hint": "lean_forward",
    "allow_interrupt": true
  },
  "ui": {
    "state": "avatar_speaking",
    "subtitle": "구체적인 성과 지표를 물어보는 중",
    "debug_tags": ["needs_metrics", "followup"]
  },
  "rubric_update": {
    "communication": 0.68,
    "specificity": 0.42,
    "structure": 0.61,
    "confidence": 0.58
  },
  "report_memory": [
    "프로젝트 역할 설명은 가능하지만 성과 수치화가 부족함"
  ]
}
```

## 21.4 Agent2 fallback

LLM timeout/schema invalid 시 fallback 질문:

```txt
좋아요. 방금 답변에서 본인이 직접 기여한 부분을 한 가지 더 구체적으로 설명해줄래요?
```

연속 실패 정책:

- 1회 실패: fallback question
- 2회 실패: simpler prompt mode
- 3회 실패: text-only deterministic interview mode

---

## 22. SpatialReal / Avatar 명세

## 22.1 기본 경로

```txt
Agent2 speak_text
  → TTS provider
  → PCM s16le mono 16kHz
  → SpatialReal Python SDK send_audio(end=True)
  → SpatialReal LiveKit egress
  → LiveKit room avatar participant
  → Browser AvatarKit UI render
```

## 22.2 SpatialReal disabled fallback

`SPATIALREAL_ENABLED=false`일 때:

- frontend는 avatar placeholder 표시
- TTS audio 또는 text bubble만 표시
- 면접 loop는 정상 작동

## 22.3 Avatar failure fallback

SpatialReal session 실패 시:

```txt
1. log avatar.provider_error
2. transition remains valid
3. send frontend_event avatar_degraded
4. play TTS audio if available
5. show speak_text as text bubble
```

## 22.4 Audio format

```txt
sample rate: 16000 Hz
channels: 1
bit depth: 16-bit
format: signed little-endian PCM
```

TTS provider가 mp3/wav를 내면 engine에서 ffmpeg/pydub/soundfile로 변환한다.

---

## 23. Frontend 명세

## 23.1 책임

- session create
- LiveKit join
- mic/camera publish
- AvatarKit UI render
- transcript/status display
- start/end controls
- report view
- error recovery UI

## 23.2 페이지

```txt
/start
/interview/:sessionId
/report/:sessionId
/error
```

## 23.3 컴포넌트

```txt
DeviceCheck
InterviewRoom
AvatarPanel
TranscriptPanel
StatusBanner
SignalDebugPanel dev-only
InterviewControls
ReportView
ErrorRecoveryCard
```

## 23.4 상태

```ts
type InterviewUiState =
  | 'idle'
  | 'creating_session'
  | 'joining_room'
  | 'waiting_for_engine'
  | 'ready'
  | 'avatar_speaking'
  | 'candidate_answering'
  | 'analyzing'
  | 'report_generating'
  | 'ended'
  | 'failed';
```

## 23.5 Frontend security

- session token은 memory/sessionStorage 중 선택. localStorage는 피한다.
- report token은 URL query에 오래 남기지 않는다.
- frontend에서 secret env 접근 금지.
- debug signal panel은 demo/dev flag에서만 켠다.

---

## 24. 보안 명세

## 24.1 Public attack surface

Public:

```txt
443 HTTPS
80 redirect
LiveKit WSS
WebRTC UDP/TURN ports
```

Private:

```txt
api internal endpoints
ai-engine
agent1
postgres
redis
```

## 24.2 Auth modes

MVP demo:

- access code 기반 session create
- session token 기반 status/report 접근
- report token 별도 발급

v1:

- user account
- OAuth/login
- per-user sessions

## 24.3 API security requirements

- rate limit session creation
- session token required for session status
- report token required for report
- admin endpoints disabled by default
- internal endpoints require internal shared secret or Docker network only
- error response에 secret/provider raw dump 금지

## 24.4 Log redaction

절대 로그 금지:

```txt
LIVEKIT_API_SECRET
SPATIALREAL_API_KEY
LLM_API_KEY
STT/TTS API keys
session_token
report_token
raw audio/video base64
full provider raw response with PII
```

---

## 25. 프라이버시 / 보존 정책

## 25.1 기본 저장 정책

기본 저장:

```txt
sessions metadata
turns
final transcripts
agent1 structured signals
agent2 outputs
reports
latency metrics
```

기본 미저장:

```txt
raw video
raw audio
full frame dumps
full provider raw logs
```

## 25.2 debug artifact

`RAW_MEDIA_STORAGE_ENABLED=true`이고 사용자 동의가 있을 때만 저장.

저장 시:

- max clip length 제한
- retention TTL 적용
- artifact 접근 로그 기록
- 삭제 API 제공

## 25.3 retention

MVP 기본:

```txt
reports: 30 days
transcripts: 30 days
debug raw artifacts: 1 day
logs: 7 days 또는 rotation
```

---

## 26. 관측성 / Healthcheck

## 26.1 Health endpoints

API:

```http
GET /healthz
GET /readyz
```

AI Engine:

```http
GET /healthz
GET /readyz
GET /metrics optional
```

Agent1:

```http
GET /healthz
GET /readyz
```

## 26.2 Metrics

필수 latency:

```txt
session_create_latency_ms
frontend_join_latency_ms
engine_attach_latency_ms
stt_partial_latency_ms
stt_final_latency_ms
agent1_nonverbal_latency_ms
agent1_evaluation_latency_ms
agent2_decision_latency_ms
tts_first_audio_latency_ms
avatar_start_latency_ms
turn_gap_ms
```

필수 counters:

```txt
sessions_created_total
sessions_failed_total
turns_completed_total
agent1_timeouts_total
agent2_fallbacks_total
avatar_failures_total
stt_failures_total
interruptions_total
```

## 26.3 docker logs 원칙

모든 서비스는 stdout/stderr에 JSON log 권장.

```json
{
  "level": "info",
  "component": "ai-engine",
  "session_id": "sess_01J...",
  "turn_id": "turn_0003",
  "event": "agent2.output_validated",
  "latency_ms": 1830,
  "created_at": "2026-05-30T03:10:00Z"
}
```

---

## 27. 운영 Runbook


## 27.0 Preflight validation

배포 전 `.env`와 포트 설정을 검증하는 스크립트를 둔다. 최소 검증 항목:

```txt
- DATABASE_URL에 asterisk placeholder 또는 <placeholder> 포함 금지
- LIVEKIT_IMAGE/COTURN_IMAGE가 latest 금지
- LIVEKIT_RTC_UDP_PORT_START/END와 livekit.yaml 값 일치
- TURN_RELAY_PORT_START/END와 turnserver.conf 값 일치
- INTERNAL_API_SECRET/SESSION_SIGNING_SECRET/REPORT_SIGNING_SECRET 기본값 금지
- SESSION_TOKEN_TTL_SECONDS=7200 및 REPORT_TOKEN_TTL_SECONDS=2592000 token contract와 불일치 금지
- PUBLIC_DOMAIN/LIVEKIT_DOMAIN DNS A/AAAA record 확인
```

예시 명령:

```bash
python infra/scripts/validate_env.py .env infra/livekit.yaml infra/turnserver.conf
```

## 27.1 최초 배포

```bash
git clone <repo> giljob
cd giljob
cp .env.example .env
# edit .env

docker compose build
docker compose up -d

docker compose ps
docker compose logs -f api ai-engine livekit
```

## 27.2 상태 확인

```bash
curl -fsS https://giljob.example.com/healthz
test "$(curl -sS -o /dev/null -w "%{http_code}" https://giljob.example.com/readyz)" = "404"

POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml ps
POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml logs --tail=100 api
POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml logs --tail=100 ai-engine
POSTGRES_PASSWORD=... LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=... TURN_DOMAIN=... TURN_REALM=... TURN_STATIC_AUTH_SECRET=... docker compose -f infra/docker-compose.yml -f infra/docker-compose.media.yml logs --tail=100 livekit
```

## 27.3 재시작

```bash
docker compose restart ai-engine
```

전체 재시작:

```bash
docker compose down
docker compose up -d
```

DB 유지하면서 재시작 가능. `down -v`는 금지.

## 27.4 백업

```bash
docker compose exec postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backups/giljob-$(date +%F).sql
```

## 27.5 흔한 장애

### 브라우저가 LiveKit에 못 붙음

확인:

```bash
docker compose logs livekit
docker compose logs caddy
```

점검:

- DNS
- TLS
- `PUBLIC_LIVEKIT_URL`
- UDP port open
- TURN 설정

### engine이 candidate track을 못 받음

점검:

- engine participant token
- room name 일치
- candidate publish 권한
- LiveKit logs
- engine logs

### SpatialReal 안 나옴

점검:

- `SPATIALREAL_ENABLED`
- API key/app/avatar/region
- TTS PCM 변환
- LiveKit egress config

### Agent2가 느림

점검:

- provider latency
- timeout/fallback count
- prompt size
- context builder가 agent1 raw dump를 넣는지 여부

---

## 28. 테스트 전략

## 28.1 Unit tests

- schema validation
- state transition CAS
- event envelope
- token generation
- Agent2 output parsing
- fallback question
- report markdown generation

## 28.2 Integration tests

- API creates session
- API issues LiveKit token
- Engine attaches to fake session
- fake STT final → Agent2 output
- fake Agent1 signal → context builder
- report creation

## 28.3 Docker smoke test — v0.3.1 corrected

Host에 publish하지 않고 `expose`만 한 service port는 host `localhost`에서 직접 curl하지 않는다. Smoke test는 public route와 container-internal exec를 분리한다.

> Implementation amendment: the smoke block below reflects the GilJob_v2 hardened readiness contract; public `/readyz` is expected to return 404 while API `/readyz` is container-internal.

```bash
POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml up -d --build
POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml ps

# Public ingress through Caddy
curl -fsS https://${PUBLIC_DOMAIN}/healthz
test "$(curl -sS -o /dev/null -w "%{http_code}" https://${PUBLIC_DOMAIN}/readyz)" = "404"
test "$(curl -sS -o /dev/null -w "%{http_code}" https://${PUBLIC_DOMAIN}/api/internal/healthz)" = "404"

# Container-internal health checks
POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=2).read()"
POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz', timeout=2).read()"
POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml exec -T ai-engine python -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/healthz', timeout=2).read()"
POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml exec -T agent1 python -c "import urllib.request; urllib.request.urlopen('http://localhost:8010/healthz', timeout=2).read()"
POSTGRES_PASSWORD=... docker compose -f infra/docker-compose.yml exec -T postgres pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}

# Optional media overlay after explicit LiveKit/TURN secrets are set
POSTGRES_PASSWORD=... LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=... TURN_DOMAIN=... TURN_REALM=... TURN_STATIC_AUTH_SECRET=... docker compose -f infra/docker-compose.yml -f infra/docker-compose.media.yml config

# TURN smoke: must be tested from a different network before demo
```

필수 수동 네트워크 검증:

- 노트북 같은 Wi-Fi에서 브라우저 join.
- 휴대폰 hotspot/5G에서 브라우저 join.
- LiveKit client stats에서 relay/TURN fallback 여부 확인.
- coturn logs에 allocation이 찍히는지 확인.

## 28.4 E2E demo test

시나리오:

1. frontend 접속
2. access code 입력
3. device check 통과
4. session 생성
5. LiveKit room join
6. opening question 표시/재생
7. candidate 답변
8. STT final 생성
9. Agent1 signal 생성
10. Agent2 follow-up 생성
11. avatar/text response
12. 3턴 반복
13. session end
14. report 표시

## 28.5 Failure injection

필수 테스트:

- Agent1 container stop
- Agent2 provider timeout
- SpatialReal disabled
- STT fake failure
- LiveKit reconnect
- candidate interrupts avatar
- DB temporarily unavailable
- Redis temporarily unavailable

---

## 29. 구현 Phase

## Phase 0 — Docker skeleton

목표: 전체 컨테이너가 뜨고 healthcheck가 돈다.

작업:

- repo layout 생성
- docker-compose.yml
- Caddyfile
- API healthz
- frontend placeholder
- ai-engine healthz
- agent1 fake healthz
- postgres/redis 연결

완료 기준:

```bash
docker compose up -d --build
docker compose ps
curl https://domain/healthz
```

## Phase 1 — Session/token/LiveKit

목표: 브라우저가 LiveKit room에 들어간다.

작업:

- `/api/sessions`
- LiveKit token 발급
- frontend device check
- LiveKit client join
- candidate mic/camera publish
- engine participant join

완료 기준:

- 브라우저에서 camera/mic publish 확인
- engine logs에 track subscribed 출력

## Phase 2 — Fake interview loop

목표: AI 없이 3턴 loop를 만든다.

작업:

- fake STT
- fake Agent1
- fake Agent2
- text/avatar placeholder response
- state machine
- event bus

완료 기준:

- 3턴 진행
- report fake 생성

## Phase 3 — Real STT + Agent2

목표: 실제 음성 전사와 실제 질문 생성.

작업:

- STT provider adapter
- Agent2 LLM adapter
- schema validation
- fallback

완료 기준:

- 지원자 답변 기반 follow-up 생성

## Phase 4 — Agent1 real integration

목표: Multi_Modal_Module 신호 반영.

작업:

- audio/video window assembler
- agent1 endpoint
- signal store
- context builder 반영

완료 기준:

- Agent2가 Agent1 signal을 사용한 follow-up 생성

## Phase 5 — SpatialReal avatar

목표: 아바타가 질문을 말한다.

작업:

- TTS adapter
- PCM conversion
- SpatialReal SDK
- LiveKit egress
- AvatarKit UI
- interruption

완료 기준:

- opening/follow-up 질문을 아바타가 재생

## Phase 6 — report/demo hardening

목표: 발표 가능한 안정화.

작업:

- report generator
- privacy/consent UI
- logs/metrics
- failure fallback
- demo runbook

완료 기준:

- 5~10분 데모 안정 실행

---

## 30. Acceptance criteria


## 30.0 P0 blocker closure checklist

Phase 0 구현 시작 전 다음이 문서와 설정에서 모두 닫혀 있어야 한다.

- [ ] Caddy가 `/api/internal/*`를 public에서 404로 막는다.
- [ ] API internal middleware가 `X-GilJob-Internal-Token` 없는 요청을 401/403 처리한다.
- [ ] LiveKit RTC range와 coturn relay range가 firewall/security group 문서와 일치한다.
- [ ] session/report token contract가 JSON schema와 DB hash 저장 방식까지 정의되어 있다.
- [ ] State transition은 CAS SQL transaction으로만 수행한다.
- [ ] Docker smoke test가 public route + `docker compose exec` 기준으로 작성되어 있다.

## 30.1 Technical acceptance

- `docker compose up -d --build`로 실행 가능
- public HTTPS 접속 가능
- DB/Redis persistent volume 동작
- LiveKit WebRTC 연결 가능
- Engine track subscribe 가능
- STT final 생성 가능
- Agent1 signal 생성 가능 또는 fake fallback
- Agent2 output schema validation 통과
- Avatar or fallback response 가능
- Report 생성 가능

## 30.2 Demo acceptance

- 발표자가 URL 접속
- 면접 시작 버튼 클릭
- 카메라/마이크 허용
- 아바타/텍스트 면접관이 첫 질문
- 지원자가 3번 답변
- 시스템이 follow-up 질문
- 종료 후 리포트 표시
- Docker logs로 각 단계 증거 제시 가능

---

## 31. 주요 리스크와 대응

## 31.1 LiveKit/TURN 네트워크 리스크

위험:

- UDP port 미개방
- NAT/firewall
- coturn 설정 오류

대응:

- 서버 방화벽 checklist 작성
- coturn logs 확인
- 모바일 네트워크로 테스트
- 최후에는 LiveKit Cloud 임시 fallback 가능하게 env 설계

## 31.2 단일 서버 장애점

위험:

- 서버 죽으면 전체 장애

대응:

- MVP에서는 수용
- healthcheck/restart policy
- DB backup
- 발표 전 freeze된 이미지 사용

## 31.3 리소스 contention

위험:

- STT/Agent1/Agent2/TTS 동시 실행으로 latency 악화

대응:

- 동시 세션 1~2개 제한
- Agent1 evaluation은 background
- timeout/fallback
- fake mode demo fallback

## 31.4 Secret 노출

위험:

- frontend build에 secret 포함
- debug route public 노출

대응:

- public env prefix 제한
- Caddy route allowlist
- internal services expose only
- secret redaction

---

## 32. 장기 split deployment로 이전 가능성

이번 결정은 MVP용이다. 장기적으로는 다음처럼 쪼갤 수 있게 경계를 유지한다.

```txt
frontend container → Cloudflare Pages
api container      → Cloudflare Worker or managed API
postgres           → managed Postgres
redis              → managed Redis
livekit            → LiveKit Cloud
ai-engine          → GPU worker pool
agent1             → GPU inference service
```

따라서 지금도 다음을 지킨다.

- frontend는 API URL/env로 backend를 바라봄
- API와 engine 사이 contract 명확화
- Agent1은 HTTP/gRPC service boundary 유지
- DB schema는 container 밖으로 이전 가능하게 설계
- LiveKit URL/API key를 env로 분리

---

## 33. 지금 당장 coder에게 줄 구현 티켓

1. Repo skeleton + docker-compose 작성
2. Caddy reverse proxy + frontend placeholder
3. FastAPI API server health/session skeleton
4. Postgres schema migration
5. Redis event bus wrapper
6. LiveKit self-host config + token 발급
7. Frontend LiveKit join/device check
8. AI Engine room join + track subscribe
9. Fake STT/Agent1/Agent2 interview loop
10. Report placeholder
11. Interruption FSM skeleton
12. Docker smoke test script

---

## 34. 최종 요약

GilJob v2 MVP는 **single-server Docker Compose**로 간다.

이 구조의 정체성은 다음이다.

```txt
한 서버에 다 올린다.
하지만 서비스를 섞지 않는다.
프론트/API/AI/Agent1/LiveKit/TURN/DB/Redis는 컨테이너로 분리한다.
외부 공개는 reverse proxy와 WebRTC/TURN에 한정한다.
AI Engine과 Agent1은 내부 서비스다.
상태 소유권은 API 서버가 가진다.
Engine은 session worker다.
Agent1은 observation sidecar다.
Agent2는 decision maker다.
```

이 방식은 졸작 MVP에서 가장 중요한 **작동성, 디버깅 가능성, 시연 안정성**을 우선한다.


---

## 35. v0.3 reviewer patch checklist

Reviewer FAIL 원인을 다음처럼 반영했다.

### Critical patched

- TURN/LiveKit 포트 불일치: **patched** — 통합 Port Matrix와 포트 불변조건 추가.
- `/api/internal/*` public 노출: **patched** — Caddy deny + internal token auth 추가.
- session/report token 계약 미완성: **patched** — opaque token, scope, TTL, hash 저장, report 발급 흐름 추가.

### High patched

- Redis backpressure 수치 부족: **patched** — maxlen/TTL/drop/retry/DLQ 정책 추가.
- StateCoordinator CAS 텍스트 수준: **patched** — atomic SQL transaction + allowed transition table 추가.
- healthcheck/smoke test 불일치: **patched** — public route와 container-internal smoke test 분리, livekit/coturn healthcheck 추가.

### Medium patched

- `latest` image tag: **patched** — `LIVEKIT_IMAGE`, `COTURN_IMAGE` pin 변수로 변경.
- identity 생성 시점: **patched** — API가 session 생성 시 candidate/engine/avatar identity를 예약한다고 명시.
- `.env` placeholder 함정: **patched** — `DATABASE_URL` 실제 예시와 preflight validation 추가.
