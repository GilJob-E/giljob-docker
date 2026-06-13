"""Per-turn storage backend for interview Q&A and analysis signals.

Two interchangeable backends share one Protocol:

- ``InMemoryTurnStore`` (default): process-local dict, no DB required.
  Unit/contract tests and quick local runs work with zero setup.
- ``PostgresTurnStore``: backed by interview_turns / interview_turn_signals
  tables (db/schema.sql). Enabled via API_DB_BACKEND=postgres.

Signals shape: the realtime flow stores the raw analysis-engine
``/realtime/turn-results`` payload per turn. Aggregation across windows
happens at report-build time in server.py::aggregate_turn_signals().
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Protocol

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"


class TurnStore(Protocol):
    def upsert_question(self, session_id: str, turn_id: int, question: str) -> None: ...
    def upsert_answer(self, session_id: str, turn_id: int, answer: str) -> None: ...
    def upsert_signals(self, session_id: str, turn_id: int, signals: dict[str, Any]) -> None: ...
    def report_rows(self, session_id: str) -> list[dict[str, Any]]: ...


# ── in-memory backend ────────────────────────────────────────────────────────
class InMemoryTurnStore:
    def __init__(self) -> None:
        self._turns: dict[tuple[str, int], dict[str, Any]] = {}
        self._signals: dict[tuple[str, int], dict[str, Any]] = {}
        self._lock = threading.RLock()

    def _entry(self, session_id: str, turn_id: int) -> dict[str, Any]:
        return self._turns.setdefault((session_id, turn_id), {"question": None, "answer": None})

    def upsert_question(self, session_id: str, turn_id: int, question: str) -> None:
        with self._lock:
            self._entry(session_id, turn_id)["question"] = question

    def upsert_answer(self, session_id: str, turn_id: int, answer: str) -> None:
        with self._lock:
            entry = self._entry(session_id, turn_id)
            if not entry.get("answer"):
                entry["answer"] = answer

    def upsert_signals(self, session_id: str, turn_id: int, signals: dict[str, Any]) -> None:
        with self._lock:
            self._entry(session_id, turn_id)  # ensure parent turn exists
            self._signals[(session_id, turn_id)] = signals

    def report_rows(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            turns = {k: dict(v) for k, v in self._turns.items() if k[0] == session_id}
            signals = {k: dict(v) for k, v in self._signals.items() if k[0] == session_id}
        turn_ids = sorted({tid for (_sid, tid) in turns} | {tid for (_sid, tid) in signals})
        return [
            {
                "turnId": turn_id,
                "question": (turns.get((session_id, turn_id)) or {}).get("question"),
                "answer":   (turns.get((session_id, turn_id)) or {}).get("answer"),
                "signals":  signals.get((session_id, turn_id)),
            }
            for turn_id in turn_ids
        ]


# ── postgres backend ─────────────────────────────────────────────────────────
class PostgresTurnStore:
    def __init__(self, dsn: str) -> None:
        import psycopg  # lazy import; only when postgres backend selected
        self._psycopg = psycopg
        self._dsn = dsn
        self._ensure_schema()

    def _connect(self):
        return self._psycopg.connect(self._dsn, autocommit=True)

    def _ensure_schema(self, attempts: int = 10, delay_seconds: float = 1.0) -> None:
        ddl = SCHEMA_PATH.read_text(encoding="utf-8")
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                with self._connect() as conn, conn.cursor() as cur:
                    cur.execute(ddl)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(delay_seconds)
        if last_error is not None:
            raise last_error

    def upsert_question(self, session_id: str, turn_id: int, question: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO interview_turns (session_id, turn_id, question)
                VALUES (%s, %s, %s)
                ON CONFLICT (session_id, turn_id)
                DO UPDATE SET question = EXCLUDED.question, updated_at = now()
                """,
                (session_id, turn_id, question),
            )

    def upsert_answer(self, session_id: str, turn_id: int, answer: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO interview_turns (session_id, turn_id, answer)
                VALUES (%s, %s, %s)
                ON CONFLICT (session_id, turn_id)
                DO UPDATE SET answer = COALESCE(interview_turns.answer, EXCLUDED.answer),
                              updated_at = now()
                """,
                (session_id, turn_id, answer),
            )

    def upsert_signals(self, session_id: str, turn_id: int, signals: dict[str, Any]) -> None:
        from psycopg.types.json import Json
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO interview_turns (session_id, turn_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (session_id, turn_id),
            )
            cur.execute(
                """
                INSERT INTO interview_turn_signals (session_id, turn_id, signals)
                VALUES (%s, %s, %s)
                ON CONFLICT (session_id, turn_id)
                DO UPDATE SET signals = EXCLUDED.signals, updated_at = now()
                """,
                (session_id, turn_id, Json(signals)),
            )

    def report_rows(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.turn_id, t.question, t.answer, s.signals
                FROM interview_turns t
                LEFT JOIN interview_turn_signals s
                  ON t.session_id = s.session_id AND t.turn_id = s.turn_id
                WHERE t.session_id = %s
                ORDER BY t.turn_id
                """,
                (session_id,),
            )
            return [
                {"turnId": row[0], "question": row[1], "answer": row[2], "signals": row[3]}
                for row in cur.fetchall()
            ]


# ── backend selection ────────────────────────────────────────────────────────
def _dsn_from_env() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    name = os.getenv("POSTGRES_DB", "giljob")
    user = os.getenv("POSTGRES_USER", "giljob")
    password = os.getenv("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


_STORE: TurnStore | None = None


def get_turn_store() -> TurnStore:
    global _STORE
    if _STORE is not None:
        return _STORE
    if os.getenv("API_DB_BACKEND", "memory").strip().lower() == "postgres":
        _STORE = PostgresTurnStore(_dsn_from_env())
    else:
        _STORE = InMemoryTurnStore()
    return _STORE
