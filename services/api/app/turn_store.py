"""Per-turn storage backend for interview Q&A and non-verbal signals.

Two interchangeable backends sit behind one small interface:

- ``InMemoryTurnStore`` (default): a process-local dict. No database required, so
  unit/contract tests and quick local runs work with zero setup.
- ``PostgresTurnStore``: the real ``interview_turns`` / ``interview_turn_signals``
  tables (db/schema.sql), enabling persistence across restarts and processes.

The backend is chosen by the ``API_DB_BACKEND`` env var ("postgres" turns on the
database; anything else stays in memory). Both are keyed by ``(session_id, turn_id)``,
matching the schema PRIMARY KEY, so the call sites never change.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Protocol

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"


def _visual_measurable(evals: list[dict[str, Any]]) -> bool:
    """True if any eval window actually saw a face (drives the denormalized column)."""
    for evaluation in evals:
        visual = evaluation.get("objective_visual") if isinstance(evaluation, dict) else None
        if isinstance(visual, dict) and (visual.get("face_seen_ratio") or 0) > 0:
            return True
    return False


class TurnStore(Protocol):
    def upsert_question(self, session_id: str, turn_id: int, question: str, metadata: dict[str, Any] | None = None) -> None: ...
    def upsert_answer(self, session_id: str, turn_id: int, answer: str, overwrite: bool = True) -> None: ...
    def upsert_signals(self, session_id: str, turn_id: int, signals: list[dict[str, Any]], giljobe_ref: object = None) -> None: ...
    def report_rows(self, session_id: str) -> list[dict[str, Any]]: ...


# ── in-memory backend ────────────────────────────────────────────────────────
class InMemoryTurnStore:
    def __init__(self) -> None:
        self._turns: dict[tuple[str, int], dict[str, Any]] = {}
        self._signals: dict[tuple[str, int], dict[str, Any]] = {}
        # Background ingest threads write while the report endpoint reads; the lock
        # keeps writes and the read snapshot from racing (no "changed size" errors).
        self._lock = threading.RLock()

    def _entry(self, session_id: str, turn_id: int) -> dict[str, Any]:
        return self._turns.setdefault((session_id, turn_id), {"question": None, "answer": None})

    def upsert_question(self, session_id: str, turn_id: int, question: str, metadata: dict[str, Any] | None = None) -> None:
        with self._lock:
            entry = self._entry(session_id, turn_id)
            entry["question"] = question
            if metadata:
                entry.update({
                    "topic": metadata.get("topic"),
                    "topicSource": metadata.get("topicSource"),
                    "hashimotoAsOfTurnId": metadata.get("hashimotoAsOfTurnId"),
                    "hashimotoTopicChanged": bool(metadata.get("hashimotoTopicChanged")),
                    "strategyReady": bool(metadata.get("strategyReady")),
                })

    def upsert_answer(self, session_id: str, turn_id: int, answer: str, overwrite: bool = True) -> None:
        with self._lock:
            entry = self._entry(session_id, turn_id)
            if overwrite or not entry.get("answer"):
                entry["answer"] = answer

    def upsert_signals(self, session_id: str, turn_id: int, signals: list[dict[str, Any]], giljobe_ref: object = None) -> None:
        with self._lock:
            self._entry(session_id, turn_id)  # ensure parent turn exists (FK parity)
            self._signals[(session_id, turn_id)] = {"signals": list(signals), "giljobeRef": giljobe_ref}

    def report_rows(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:  # take a consistent snapshot under the lock
            turns = {key: dict(value) for key, value in self._turns.items() if key[0] == session_id}
            signals = {key: dict(value) for key, value in self._signals.items() if key[0] == session_id}
        turn_ids = sorted({tid for (_sid, tid) in turns} | {tid for (_sid, tid) in signals})
        rows: list[dict[str, Any]] = []
        for turn_id in turn_ids:
            qa = turns.get((session_id, turn_id)) or {}
            signal_row = signals.get((session_id, turn_id)) or {}
            rows.append({
                "turnId": turn_id,
                "question": qa.get("question"),
                "answer": qa.get("answer"),
                "topic": qa.get("topic"),
                "topicSource": qa.get("topicSource"),
                "hashimotoAsOfTurnId": qa.get("hashimotoAsOfTurnId"),
                "hashimotoTopicChanged": qa.get("hashimotoTopicChanged"),
                "strategyReady": qa.get("strategyReady"),
                "signals": signal_row.get("signals"),
            })
        return rows


# ── postgres backend ─────────────────────────────────────────────────────────
class PostgresTurnStore:
    def __init__(self, dsn: str) -> None:
        import psycopg  # lazy: only imported when the DB backend is selected

        self._psycopg = psycopg
        self._dsn = dsn
        self._ensure_schema()

    def _connect(self):
        return self._psycopg.connect(self._dsn, autocommit=True)

    def _ensure_schema(self, attempts: int = 10, delay_seconds: float = 1.0) -> None:
        ddl = SCHEMA_PATH.read_text(encoding="utf-8")
        last_error: Exception | None = None
        for _ in range(attempts):  # tolerate Postgres still warming up at boot
            try:
                with self._connect() as conn, conn.cursor() as cur:
                    cur.execute(ddl)
                return
            except Exception as exc:  # noqa: BLE001 - retry transient startup errors
                last_error = exc
                time.sleep(delay_seconds)
        if last_error is not None:
            raise last_error

    def upsert_question(self, session_id: str, turn_id: int, question: str, metadata: dict[str, Any] | None = None) -> None:
        metadata = metadata or {}
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO interview_turns
                    (session_id, turn_id, question, topic, topic_source,
                     hashimoto_as_of_turn_id, hashimoto_topic_changed, strategy_ready)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id, turn_id)
                DO UPDATE SET question = EXCLUDED.question,
                              topic = EXCLUDED.topic,
                              topic_source = EXCLUDED.topic_source,
                              hashimoto_as_of_turn_id = EXCLUDED.hashimoto_as_of_turn_id,
                              hashimoto_topic_changed = EXCLUDED.hashimoto_topic_changed,
                              strategy_ready = EXCLUDED.strategy_ready,
                              updated_at = now()
                """,
                (
                    session_id, turn_id, question,
                    metadata.get("topic"),
                    metadata.get("topicSource"),
                    metadata.get("hashimotoAsOfTurnId"),
                    bool(metadata.get("hashimotoTopicChanged")),
                    bool(metadata.get("strategyReady")),
                ),
            )

    def upsert_answer(self, session_id: str, turn_id: int, answer: str, overwrite: bool = True) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            if overwrite:
                cur.execute(
                    """
                    INSERT INTO interview_turns (session_id, turn_id, answer)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (session_id, turn_id)
                    DO UPDATE SET answer = EXCLUDED.answer, updated_at = now()
                    """,
                    (session_id, turn_id, answer),
                )
            else:
                # Backfill must not clobber an answer already stored for this turn.
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

    def upsert_signals(self, session_id: str, turn_id: int, signals: list[dict[str, Any]], giljobe_ref: object = None) -> None:
        from psycopg.types.json import Json

        rows = list(signals)
        with self._connect() as conn, conn.cursor() as cur:
            # Guarantee the parent turn row exists before inserting signals (FK).
            cur.execute(
                "INSERT INTO interview_turns (session_id, turn_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (session_id, turn_id),
            )
            cur.execute(
                """
                INSERT INTO interview_turn_signals
                    (session_id, turn_id, signals, window_count, visual_measurable, giljobe_ref)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id, turn_id)
                DO UPDATE SET signals = EXCLUDED.signals,
                              window_count = EXCLUDED.window_count,
                              visual_measurable = EXCLUDED.visual_measurable,
                              giljobe_ref = EXCLUDED.giljobe_ref,
                              updated_at = now()
                """,
                (session_id, turn_id, Json(rows), len(rows), _visual_measurable(rows),
                 None if giljobe_ref is None else str(giljobe_ref)),
            )

    def report_rows(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.turn_id, t.question, t.answer, t.topic, t.topic_source,
                       t.hashimoto_as_of_turn_id, t.hashimoto_topic_changed,
                       t.strategy_ready, s.signals
                FROM interview_turns t
                LEFT JOIN interview_turn_signals s
                  ON t.session_id = s.session_id AND t.turn_id = s.turn_id
                WHERE t.session_id = %s
                ORDER BY t.turn_id
                """,
                (session_id,),
            )
            fetched = cur.fetchall()
        return [
            {
                "turnId": row[0],
                "question": row[1],
                "answer": row[2],
                "topic": row[3],
                "topicSource": row[4],
                "hashimotoAsOfTurnId": row[5],
                "hashimotoTopicChanged": row[6],
                "strategyReady": row[7],
                "signals": row[8],
            }
            for row in fetched
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
    """Return the process-wide turn store, building it on first use.

    A failed Postgres connection is not memoized, so the next call retries once the
    database is reachable (the server stays up through a slow/late database).
    """
    global _STORE
    if _STORE is not None:
        return _STORE
    if os.getenv("API_DB_BACKEND", "memory").strip().lower() == "postgres":
        _STORE = PostgresTurnStore(_dsn_from_env())
    else:
        _STORE = InMemoryTurnStore()
    return _STORE
