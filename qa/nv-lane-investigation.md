# 3초 NV 레인 미동작 조사 (2026-06-11, PR11 빌드 / GilJobE e0671f5) — ✅ 해결

## 증상
`kor.mp4` 턴에서 window 레코드 13개 전부 `nonverbal=null`, `objective_nonverbal=null`.
eval(16s) 레코드의 비평/objective_vocal/objective_visual은 정상.

## 근본 원인 (확정, 2026-06-11)
**"장수 프로세스" 가설은 교란변수였다.** 진짜 원인은 poll 클럭(벽시계, t0=첫 track 구독) vs
지연 도착 비디오의 구조적 경쟁:

1. lk **파일** 퍼블리시는 비디오를 ~5s GOP 버스트로 늦게 딜리버한다(34s에 19장, PLI 반복).
2. `TurnWindower.poll()`은 3s 윈도우 마감 시점에 프레임 버퍼를 한 번 자르고 그리드를 전진 —
   슬라이스가 비면(`if frames:`) NV를 **영구 스킵**했다. 늦게 온 프레임은 버퍼에 쌓이기만 함.
3. 3s 윈도우는 자기 프레임 도착 전에 마감(지연 ~5s > 3s+0.5) → 13/13 null.
   16s eval은 마감이 충분히 늦어 이전 버스트가 도착해 있음 → 정상. (모든 기존 증거와 정합)
4. "새 프로세스 재현은 정상"의 정체: 발행 **중간** join → 키프레임 버스트 즉시 도착 → [0,3)만
   생존(_do_nv 1회 — 프레임 4개 중 1개 윈도우만 회수된 것도 사실은 같은 버그의 부분 증상).
   브라우저 웹캠(slice-10)은 부드러운 실시간 딜리버리라 미발현.

## 수정 (GilJobE `windowing.py` — nv catch-up)
마감 때 프레임이 없던 윈도우를 `_nv_starved`로 기억하고, 다음 poll/end_turn에서 프레임이
도착해 있으면 NV를 늦게라도 제출(레코드는 t 자기기술 — recorder 페어링·소비자 정렬 유지).
stt는 재제출 안 함(중복 전사 방지). 정시 경로 지연 추가 0(★실시간 1순위).
회귀 테스트: `tests/test_windowing.py::test_late_video_frames_caught_up_after_window_close`.

## 검증 (QA 스택, 같은 장수 서버 + 같은 lk 파일 퍼블리시)
- `qa/kor-signals-nv-fix.json`: window 13개 중 **nonverbal/objective_nonverbal 7개 채움**
  (수정 전 0개). 7개 전부 catch-up 로그와 1:1 대응("nv catch-up: …1개 윈도우 회수" ×7).
- 누락 6개 = **프레임이 아예 안 온 윈도우**(dense 레인 전체 수신 17장/38s — lk 파일 퍼블리시
  병리, 위 1번). 엔진이 회수할 프레임 자체가 없음. 브라우저 웹캠에선 전 윈도우 커버 기대.
- turn_end.eval=null(이번 런)은 하니스 아티팩트: 미디어 38s 종료 후 ~17s 유휴 뒤 stop →
  tail 구간에 미디어 0 → `frames and pcm` 게이트가 올바르게 스킵. 실 사용(발화 직후 stop)에선
  tail에 미디어가 있다. 단, 버스트 딜리버리에선 마지막 GOP 미도착 시 여전히 null 가능 —
  eval/tail 레인 catch-up은 미구현(16s 지연은 미관측, compact tail은 늦은 평가 가치가 낮음).

## 정식 반영 (2026-06-11, PR #11 머지 후)
- GilJobE `c7dd741`(수정)·`6bef78b`(tip) — origin 브랜치 `fix/nv-catchup`으로 푸시
  (main 직푸시는 세션 권한 차단 — **GilJobE main을 6bef78b로 fast-forward 필요**, 사용자 액션).
- giljob-docker **PR #14 오픈**: 핀 e0671f5→6bef78b(7곳+가드). 계약 78/78 · build+nobody 스모크 ·
  **클린 이미지 라이브 재검증 7/13 + catch-up 로그 7/7** (`qa/kor-signals-pin-verify.json`).
- QA 컨테이너는 핫패치가 아니라 **정식 핀 이미지로 재빌드됨**(핫패치 흔적 제거).

## 환경 주의
- lk 파일 퍼블리시 영상 열화(GOP 버스트)는 여전한 테스트 한계 — 영상 의존 기능 판단 시
  브라우저 웹캠 경로로 교차 확인할 것.
