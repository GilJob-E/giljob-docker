# .vision_test 손가락 시퀀스 붕괴 — 원인 격리 (2026-06-13)

질문: `.vision_test`는 손가락이 3번(4→2→5) 바뀌는 영상. 3fps에서 hands 레인이 시퀀스를 잡아야
하고 원래 잡았는데, 제품경로 런(`../2026-06-13-vision-test-productpath{,-noguard}`)에선 `[4]`로
붕괴. 최근 머지/RNAS 변경이 오염시킨 건가?

## 실험: 그라운더에 클립을 직접 통과(해상도 스윕) — `groundtruth.json`

하니스 `vt_groundtruth.py`가 클립을 3fps로 디코드해 **라이브와 동일한** VisionGrounder
(add_frame→window_metrics→aggregate_hands→_finger_segments)에 통과. 차이는 '전달'뿐(디스크 디코드).

| 해상도 | hand_seen | **finger_sequence** |
|---|---|---|
| native 1920x1080 | 0.31 | **[4, 2, 5]** |
| 960x540 | 0.31 | **[4, 2, 5]** |
| 640x480 레터박스(하니스와 동일) | 0.29 | **[4, 2, 5]** |

손가락 시퀀스는 **모든 해상도에서**(하니스 640x480 포함) 완전히 잡힌다. segments: 4(9.3~10.7s)
→2(12~13s)→5(14.3~15.3s) — 실제 손동작은 클립 9~17초 구간.

## 결론 — 클립·알고리즘·해상도 무죄, **라이브 read-out 게이팅이 원인**

1. **그라운더는 dense 프레임에서 [4,2,5]를 정상 포착**(3fps, 640x480에서도). 즉 비전 알고리즘·
   해상도·클립은 멀쩡하다.
2. **제품경로가 `[4]`로 붕괴한 이유 = 비전 집계가 문장(sentence) 구간에만 붙는데 eval 윈도우가
   OFF라서.** 근거:
   - `emit/handoff.py:361` `build_turn_handoff`: `visual_in = [r.visual for r in sents] or [evals]`
     → 턴 visual은 **문장 visual의 합집합**(eval 없으면 폴백 없음). turnHandoff.visual.windows=5 =
     문장 5개.
   - 라이브 문장 구간: (5.4,5.6)(5.6,8.91)(18.46,20.08)(22.86,23.06)(23.06,23.96) →
     **8.91~18.46s = 9.55초 공백**. 손가락 4→2→5(answer-time ~7.7~15.7s)가 바로 이 **무발화
     공백**에서 진행된다.
   - 후보가 손가락을 **말없이** 보여주는 구간이라 문장이 없고 → 비전 read가 안 일어남.
     "4"만 문장(5.6~8.91s) 꼬리에 걸려 살아남고, "2"·"5"는 공백에 떨어져 유실.
   - `GILJOBE_EVAL_GRID=off`(배포 기본값, 커밋 bf53a3e "eval off")라 **전사-독립 16s eval read**가
     없다 → 무발화 공백을 덮을 길이 없음.
3. **그래서 "최근 변경이 오염"은 사실** — RNAS/문장 레인 중심 + eval-off 정렬(realtime reconcile)이
   "말 안 하고 제스처만 하는 구간"의 비전 read를 구조적으로 누락시킨다. dense 프레임은 캡처됐지만
   읽히지 않는다.

## 수정 방향 (택1, 후속)

- **A. turn_end에 전사-독립 풀턴 비전 read 추가** — eval-off(저지연) 유지하면서, 턴 종료 시
  grounder.window_metrics(0, turn_dur)로 손가락/제스처 시퀀스를 1회 집계해 turnHandoff.visual에
  병합. 문장 공백을 덮음. (권장 — 레이턴시 영향 최소, 손동작은 LLM 비평이 아니라 수치 집계라 저렴)
- **B. eval 윈도우 부분 재활성** — GILJOBE_EVAL_GRID=on. 무발화 공백 덮지만 stop→turn_end 지연
  +1.2s 복귀(eval-off로 얻은 이득 반납).
- **확인 실험**: B를 한 턴만 켜고 재실행하면 [4,2,5] 복원 여부로 진단 확정 가능(스택 토글+토큰 1턴).

참고: groundtruth 초기 런은 프레임을 너무 빨리 먹여 load-shedding(45장 드롭, max_backlog=30)으로
오염됐었음 → max_backlog 무력화 후 전수 측정이 위 표(shed 0).
