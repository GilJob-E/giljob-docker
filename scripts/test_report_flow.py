"""Report pipeline end-to-end unit test."""
import sys, json
sys.path.insert(0, 'services/api')

# ── 1. InMemoryTurnStore ──────────────────────────────────────────────────────
from app.turn_store import InMemoryTurnStore
store = InMemoryTurnStore()

store.upsert_question('sess-1', 1, '자기소개를 해주세요.')
store.upsert_answer('sess-1', 1, '저는 4년차 백엔드 엔지니어입니다.')
store.upsert_signals('sess-1', 1, {
    'transcriptSignals': {
        'speech_rate_syllables_per_sec': 5.5,
        'pitch_hz': 220.0,
        'pause_count_long': 1,
    },
    'visionSignals': {
        'smile_ratio': 0.20,
        'gaze_off_ratio': 0.30,
        'blink_count': 2,
        'face_seen_ratio': 0.9,
    },
})
store.upsert_question('sess-1', 2, '어떤 기술을 사용했나요?')
store.upsert_answer('sess-1', 2, 'Python과 PostgreSQL을 사용했습니다.')
# turn 2 has no signals (analysis not yet complete)

rows = store.report_rows('sess-1')
assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}"
assert rows[0]['question'] == '자기소개를 해주세요.', "turn1 question mismatch"
assert rows[1]['signals'] is None, f"turn2 signals should be None, got {rows[1]['signals']}"
print("[TurnStore] OK — 2 rows, turn2 signals=None as expected")

# ── 2. aggregate_turn_signals ─────────────────────────────────────────────────
import server as s

agg = s.aggregate_turn_signals(rows[0]['signals'])
assert agg['rate'] == 5.5,   f"rate mismatch: {agg['rate']}"
assert agg['pitch'] == 220.0, f"pitch mismatch: {agg['pitch']}"
assert agg['pause'] == 1,     f"pause mismatch: {agg['pause']}"
assert agg['visualMeasurable'] is True, f"visualMeasurable mismatch"
assert abs(agg['smile'] - 20.0) < 0.01, f"smile mismatch: {agg['smile']}"
assert abs(agg['gaze']  - 30.0) < 0.01, f"gaze mismatch:  {agg['gaze']}"
assert agg['blink'] == 2, f"blink mismatch: {agg['blink']}"
print(f"[aggregate_turn_signals] OK — rate={agg['rate']} pitch={agg['pitch']} smile={agg['smile']}% gaze={agg['gaze']}%")

# No signals → safe default
agg_empty = s.aggregate_turn_signals(None)
assert agg_empty == {'visualMeasurable': False}, f"empty signals: {agg_empty}"
print("[aggregate_turn_signals] OK — None input → {visualMeasurable: False}")

# ── 3. build_report shape (report.js 호환 포맷) ───────────────────────────────
import app.turn_store as _ts
_ts._STORE = store

report = s.build_report('sess-1')
assert report['interviewId'] == 'sess-1'
assert report['turnCount'] == 2
assert report['complete'] is False, "complete should be False (turn2 has no signals)"

t1 = report['turns'][0]
assert t1['turnId'] == 1
assert t1['question'] == '자기소개를 해주세요.'
assert t1['answer'] == '저는 4년차 백엔드 엔지니어입니다.'

vocal = t1['metrics']['vocal']
visual = t1['metrics']['visual']
coverage = t1['metrics']['coverage']

assert vocal.get('speechRateSylPerSec') == 5.5,  f"vocal rate: {vocal}"
assert vocal.get('pitchMeanHz') == 220.0,         f"vocal pitch: {vocal}"
assert vocal.get('pauseCount') == 1,              f"vocal pause: {vocal}"
assert coverage['visualMeasurable'] is True,      f"coverage: {coverage}"
# smile/gaze are ratio 0-1 in report.js format (we divide ×100 back)
assert abs(visual.get('smileMean', 0) - 0.20) < 0.001,   f"smileMean: {visual}"
assert abs(visual.get('gazeOffMean', 0) - 0.30) < 0.001, f"gazeOffMean: {visual}"
assert visual.get('blinkCount') == 2, f"blinkCount: {visual}"

t2 = report['turns'][1]
assert t2['metrics']['vocal'] == {}, f"turn2 vocal should be empty: {t2['metrics']['vocal']}"
assert t2['metrics']['coverage']['visualMeasurable'] is False
print(f"[build_report] OK — turnCount=2, complete=False, vocal/visual shapes correct")
print(f"  turn1: vocal={vocal}  coverage={coverage}")
print(f"  turn2: vocal=empty  coverage={t2['metrics']['coverage']}")

# ── 4. GET /api/interviews/:id/report over HTTP ───────────────────────────────
import threading, urllib.request, json as _json
from http.server import ThreadingHTTPServer
from server import Handler

srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
t = threading.Thread(target=srv.serve_forever, daemon=True)
t.start()
base = f"http://127.0.0.1:{srv.server_address[1]}"

try:
    # Empty interview
    with urllib.request.urlopen(f"{base}/api/interviews/no-such-id/report", timeout=5) as r:
        data = _json.loads(r.read())
    assert data['turnCount'] == 0
    assert data['complete'] is False
    print(f"[HTTP GET /report] OK — unknown id → turnCount=0, complete=False")

    # Known interview
    with urllib.request.urlopen(f"{base}/api/interviews/sess-1/report", timeout=5) as r:
        data = _json.loads(r.read())
    assert data['turnCount'] == 2
    assert data['turns'][0]['metrics']['vocal']['speechRateSylPerSec'] == 5.5
    print(f"[HTTP GET /report] OK — sess-1 → turnCount=2, vocal present")

    # Invalid id (path traversal)
    import urllib.error
    try:
        with urllib.request.urlopen(f"{base}/api/interviews/../etc/report", timeout=5) as r:
            body = r.read()
        print(f"[HTTP GET /report] FAIL — should have rejected path traversal, got {r.status}")
    except urllib.error.HTTPError as e:
        assert e.code in (400, 404), f"Expected 400/404 for path traversal, got {e.code}"
        print(f"[HTTP GET /report] OK — path traversal rejected with {e.code}")

    # Internal path blocked
    try:
        with urllib.request.urlopen(f"{base}/api/internal/interviews/x/report", timeout=5) as r:
            print(f"[HTTP GET /report] FAIL — internal path should be blocked")
    except urllib.error.HTTPError as e:
        assert e.code == 404
        print(f"[HTTP GET /report] OK — internal path → 404")

finally:
    srv.shutdown()
    srv.server_close()
    t.join(timeout=2)

print()
print("All report flow checks PASSED")
