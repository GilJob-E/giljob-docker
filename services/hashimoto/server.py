#!/usr/bin/env python3
"""GilJob v2 hashimoto strategy engine service (internal sidecar).

Reference-only interviewer strategy provider. Consumes per-turn final transcripts
(keyed by session_id + turn_id) and maintains one LowLatencyHashimotoEngine per
session. The AI engine (Agent2) pulls the latest strategy package on demand; this
service never generates the interview question, tone, avatar, UI, or rubric.

Boundary (see AGENTS.md):
- input  : stt.final transcript text only.
- output : a reference strategy package, pulled via GET /strategy (non-blocking).
- state  : one engine per session_id (registry); (session_id, turn_id) dedup.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from engine.low_latency import LowLatencyHashimotoEngine
from models.io import EngineInput, HashimotoConfig

SERVICE_NAME = os.getenv("SERVICE_NAME", "hashimoto")
PORT = int(os.getenv("SERVICE_PORT", "8200"))
ANALYSIS_MODEL = os.getenv("HASHIMOTO_ANALYSIS_MODEL") or None

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(SERVICE_NAME)

app = FastAPI(title="GilJob v2 hashimoto", description="Interviewer strategy engine (reference-only)")


# ── Session registry (멀티테넌트: session_id → 전용 엔진) ──────────────────────
# 세션당 추적할 turn_id 상한. 초과 시 가장 오래된 것부터 제거(LRU)해 메모리 누수 방지.
# 한 면접 세션의 턴 수는 수십~수백 규모이므로 충분한 여유.
_MAX_SEEN_TURN_IDS = 2048


@dataclass
class _Session:
    engine: LowLatencyHashimotoEngine
    # 접수된 모든 turn_id를 기억(단건 last_turn_id가 아니라 집합) → 재시도/순서 뒤바뀜에도 dedup.
    # OrderedDict를 LRU로 사용: 값은 미사용(set 의미), 상한 초과 시 oldest pop.
    seen_turn_ids: "OrderedDict[str, None]" = field(default_factory=OrderedDict)

    def is_duplicate_turn(self, turn_id: str) -> bool:
        """이미 접수된 turn_id면 True. out-of-order 정책: 한 번 접수된 turn_id는
        이후 어떤 순서로 다시 들어와도(예: turn_1 → turn_2 → turn_1 재시도) 중복으로 본다."""
        return turn_id in self.seen_turn_ids

    def mark_turn(self, turn_id: str) -> None:
        """turn_id를 접수 기록에 추가하고 LRU 상한을 유지한다."""
        self.seen_turn_ids[turn_id] = None
        while len(self.seen_turn_ids) > _MAX_SEEN_TURN_IDS:
            self.seen_turn_ids.popitem(last=False)


_sessions: Dict[str, _Session] = {}


def _build_engine(
    resume_text: Optional[str],
    topics: Optional[List[str]],
    topic_count: int,
    config: Optional[HashimotoConfig],
) -> LowLatencyHashimotoEngine:
    """엔진 생성(동기·블로킹: from_resume가 topic 추출 LLM을 1회 호출).
    테스트는 이 함수를 monkeypatch해 네트워크 없이 fake 엔진을 주입한다."""
    if topics:
        return LowLatencyHashimotoEngine.from_topics(topics, config=config)
    if resume_text:
        return LowLatencyHashimotoEngine.from_resume(resume_text, topic_count, config=config)
    raise ValueError("resume_text 또는 topics 중 하나가 필요합니다.")


# ── Request models ────────────────────────────────────────────────────────────
# internal-only 서비스라도 빈/거대 payload·과도한 topic 입력은 비용·메모리 문제를 일으키므로
# 식별자·텍스트 길이와 topic 개수에 상한을 둔다.
_MAX_ID_LEN = 128
_MAX_TEXT_LEN = 20_000
_MAX_TOPIC_LEN = 500
_MAX_TOPICS = 50


class OpenSessionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=_MAX_ID_LEN)
    resume_text: Optional[str] = Field(default=None, max_length=_MAX_TEXT_LEN)
    topics: Optional[List[str]] = Field(default=None, max_length=_MAX_TOPICS)
    topic_count: int = Field(default=3, ge=1, le=_MAX_TOPICS)
    config: Optional[HashimotoConfig] = None

    @field_validator("topics")
    @classmethod
    def _check_topic_items(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """각 topic은 비어 있지 않고 _MAX_TOPIC_LEN 이하여야 한다."""
        if v is None:
            return v
        for t in v:
            if not t or not t.strip():
                raise ValueError("빈 topic은 허용되지 않습니다.")
            if len(t) > _MAX_TOPIC_LEN:
                raise ValueError(f"topic 길이는 {_MAX_TOPIC_LEN}자를 넘을 수 없습니다.")
        return v


class SubmitTurnRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=_MAX_ID_LEN)
    turn_id: str = Field(min_length=1, max_length=_MAX_ID_LEN)
    text: str = Field(min_length=1, max_length=_MAX_TEXT_LEN)


class EndSessionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=_MAX_ID_LEN)


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.post("/session")
async def open_session(req: OpenSessionRequest) -> JSONResponse:
    """세션 시작: session_id별 엔진을 1회 생성(턴 루프 밖). 멱등(중복 생성 금지)."""
    existing = _sessions.get(req.session_id)
    if existing is not None:
        eng = existing.engine
        return JSONResponse(
            status_code=200,
            content={
                "session_id": req.session_id,
                "current_topic": eng.current_topic,
                "topics": [eng.current_topic, *eng.remaining_topics],
                "already_open": True,
            },
        )
    config = req.config or (HashimotoConfig(analysis_model=ANALYSIS_MODEL) if ANALYSIS_MODEL else None)
    loop = asyncio.get_running_loop()
    try:
        engine = await loop.run_in_executor(
            None, _build_engine, req.resume_text, req.topics, req.topic_count, config
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await engine.start()
    _sessions[req.session_id] = _Session(engine=engine)
    return JSONResponse(
        status_code=201,
        content={
            "session_id": req.session_id,
            "current_topic": engine.current_topic,
            "topics": [engine.current_topic, *engine.remaining_topics],
        },
    )


@app.post("/submit_turn")
async def submit_turn(req: SubmitTurnRequest) -> JSONResponse:
    """STT 최종 전사 투입(비차단). (session_id, turn_id) dedup."""
    s = _sessions.get(req.session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if s.is_duplicate_turn(req.turn_id):
        return JSONResponse(
            status_code=200,
            content={"accepted": False, "reason": "duplicate_turn",
                     "session_id": req.session_id, "turn_id": req.turn_id},
        )
    s.mark_turn(req.turn_id)
    s.engine.submit_turn(EngineInput(stt_text=req.text, turn_id=req.turn_id))
    return JSONResponse(
        status_code=202,
        content={"accepted": True, "session_id": req.session_id, "turn_id": req.turn_id},
    )


@app.get("/strategy")
async def strategy(session_id: str = Query(...)) -> JSONResponse:
    """최신 전략 패키지 pull(참고 전용·비차단). 분석 전이면 ready=false."""
    s = _sessions.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    pkg = s.engine.latest_strategy
    if pkg is None:
        return JSONResponse(status_code=200, content={
            "ready": False, "session_id": session_id, "as_of_turn_id": None,
            "session_complete": s.engine.session_complete, "interaction_strategy": None,
        })
    return JSONResponse(status_code=200, content={
        # 완료된 전략의 기준 턴(submit 시점이 아니라 워커가 분석을 끝낸 턴). 제출만 되고 아직
        # 분석 미완료인 turn_id는 여기 반영되지 않는다 → as_of_turn_id가 항상 패키지와 일치.
        "ready": True, "session_id": session_id,
        "as_of_turn_id": s.engine.latest_strategy_turn_id,
        "session_complete": s.engine.session_complete,
        "interaction_strategy": pkg.interaction_strategy,
    })


@app.post("/session/end")
async def end_session(req: EndSessionRequest) -> JSONResponse:
    """세션 종료: 엔진 워커 정리(누수 방지) + registry 제거. 멱등."""
    s = _sessions.pop(req.session_id, None)
    if s is None:
        return JSONResponse(status_code=200, content={"already_closed": True, "session_id": req.session_id})
    verified = len(s.engine.verified_archive)
    refused = len(s.engine.refused_archive)
    await s.engine.stop()
    return JSONResponse(status_code=200, content={
        "session_id": req.session_id, "verified_count": verified, "refused_count": refused,
    })


@app.get("/healthz")
@app.get("/readyz")
async def healthz() -> JSONResponse:
    return JSONResponse(status_code=200, content={
        "service": SERVICE_NAME, "status": "ok",
        "active_sessions": len(_sessions),
        "model": ANALYSIS_MODEL or "gemini-3.1-flash-lite",
        "geminiKeyConfigured": bool(os.getenv("GEMINI_API_KEY")),
    })


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
