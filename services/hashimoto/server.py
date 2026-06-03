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
from dataclasses import dataclass
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from engine.low_latency import LowLatencyHashimotoEngine
from models.io import EngineInput, HashimotoConfig

SERVICE_NAME = os.getenv("SERVICE_NAME", "hashimoto")
PORT = int(os.getenv("SERVICE_PORT", "8200"))
ANALYSIS_MODEL = os.getenv("HASHIMOTO_ANALYSIS_MODEL") or None

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(SERVICE_NAME)

app = FastAPI(title="GilJob v2 hashimoto", description="Interviewer strategy engine (reference-only)")


# ── Session registry (멀티테넌트: session_id → 전용 엔진) ──────────────────────
@dataclass
class _Session:
    engine: LowLatencyHashimotoEngine
    last_turn_id: Optional[str] = None


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
class OpenSessionRequest(BaseModel):
    session_id: str
    resume_text: Optional[str] = None
    topics: Optional[List[str]] = None
    topic_count: int = 3
    config: Optional[HashimotoConfig] = None


class SubmitTurnRequest(BaseModel):
    session_id: str
    turn_id: str
    text: str


class EndSessionRequest(BaseModel):
    session_id: str


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
    if s.last_turn_id == req.turn_id:
        return JSONResponse(
            status_code=200,
            content={"accepted": False, "reason": "duplicate_turn",
                     "session_id": req.session_id, "turn_id": req.turn_id},
        )
    s.last_turn_id = req.turn_id
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
        "ready": True, "session_id": session_id, "as_of_turn_id": s.last_turn_id,
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
