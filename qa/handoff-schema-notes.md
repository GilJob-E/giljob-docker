# LLM 핸드오프 스키마 v1 — 설계 노트 (대개편 #2, 2026-06-11)

> 산출물: `qa/turn-handoff-kor.json` · `qa/turn-handoff-kor-latency.json` ·
> `qa/turn-handoff-kor-nvfix.json` (NV 버그 수정 후 런 — nonverbal 섹션 첫 실데이터)
> 생성기(프로토타입): `giljobe/.dev/llm_handoff/make_turn_handoff.py` (입력 = `/analysis/signals` 페이로드)
> 문제: next-question LLM에 `transcript_full`(2,000자 절단)만 감 — eval 비평·objective 실측치 전부 유실.

## `turn_handoff` 스키마 (v1)

| 키 | 내용 | 출처 |
|---|---|---|
| `transcript` | 턴 전체 전사, 무절단 | turn_end.transcript_full |
| `speech` | objective_vocal **턴 집계** — per-window와 같은 shape | eval 윈도우들 |
| `visual` | objective_visual **턴 집계** — 〃 | eval 윈도우들 |
| `nonverbal` | 3s nv read 상태 분포(states 비율·intensity 평균·최근 note 3) | window 레코드 (현재 NV버그로 0) |
| `analysis` | eval 비평 텍스트, 시간 참조 보존 — concerns/highlights/verbal | eval 레코드 |
| `prompt_block` | **ai-engine이 `"\n".join`으로 끼우는 한국어 렌더** (~1,000자). JSON엔 **줄 배열**로 실음 — QA에서 사람이 바로 읽게(`\n` 이스케이프 한 줄 덩어리 방지) | describe_vocal/visual 재사용 |
| `meta` | 윈도우 수·문자 수·`flags`(비평↔실측 모순) | — |

### 핵심 결정
1. **집계는 순수 파이썬, LLM 호출 0** — turn_end 시점 sub-ms. 1순위(레이턴시)에 비용 0.
2. **집계 shape = per-window shape** → 프로덕션 `describe_vocal`/`describe_visual`을 그대로 재사용해
   `prompt_block` 렌더(참조범위·관측불가 차단 문구 포함, 로직 드리프트 0).
3. **집계 규칙**: 카운트(음절·쉼·깜빡임·제스처)=합산 / 비율(발화·조음속도)=합산 후 재계산
   (평균-의-비율 함정 — 6.6s 꼬리 윈도우가 16s와 같은 가중을 받으면 왜곡) / 분포 통계(F0 sd·PDQ
   =유성프레임 가중, smile·gaze=검출프레임 가중, 에너지 추세=길이 가중) / smile_max·최장쉼=병합 극값.
   풀링 SD 대신 "윈도우 내 변동의 가중평균"(윈도우 간 declination 섞임 방지). 미검출 윈도우는
   coverage(seen_ratio)에만 반영, 특징 평균에서 제외.
4. **`analysis`에서 vocal/visual 텍스트 축은 버림** — 수치-번역이거나 수치와 모순(아래). verbal 3축
   +critique+key_observations만 유지. critique는 `(0~16초)` 시간 참조를 붙여 전달.
5. **모순 자동 플래그(맛보기)**: "단조" 주장 ∧ sd_semitone≥2 → `meta.flags`. 플래그 존재 시
   prompt_block 끝에 "[실측 우선 규칙]" 1줄 추가(소비자 LLM이 수치를 정본으로 보게).
6. `transcript` 무절단 — 절단은 소비자(ai-engine `_safe_str`) 정책이지 스키마가 아님.

## 실측 결과 (kor.mp4, 38s 턴)

- `prompt_block` ≈ **1,011자** (전사 317자 별도) — Gemini 입력 증가분은 입력 토큰이라 레이턴시 영향 미미.
- **모순 플래그**: kor 런 3/3 윈도우, latency 런 2/3 윈도우가 "단조" 주장 — 실측 sd_semitone
  4.3~8.35(2 미만=단조 기준 전부 위반). slice-15의 "단조 상투구 잔존" 그대로 재확인.
- 집계 sanity: 음절 213개/38.63s → 5.51 syl/s(쉼 포함), 조음 6.18(한국어 보통 5.8~6.9 내),
  진짜 쉼(≥0.25s) 1회·짧은 휴지 31회, 얼굴 검출 71%(마지막 윈도우 미검출이 coverage로 반영).

## 제안: eval 프롬프트 간소화 (다음 단계, 라이브 A/B 필요)

vocal/visual 텍스트 축은 eval 출력 문자의 **36%**인데 (a) objective 레인이 같은 내용을 더 정확히
측정하고 (b) 실측 그라운딩을 주입해도 5/6 윈도우에서 모순("단조")을 냈다. 제거하면:
- `EVAL_SYSTEM` 출력 키: `verbal{3} + critique + key_observations` (vocal/visual 삭제)
- 출력 토큰 ~36%↓ → 생성 ~90 tok/s 기준 **윈도당 eval 꼬리 ~2초 단축** 추정
  (관측된 윈도 종료→eval 도착 6~9s의 직접 절감 — 1순위 목표 정합)
- 멀티모달 입력은 유지(critique가 전달력 문제를 짚을 수 있게), 전달력 *수치*는 핸드오프가 운반.
→ 검증: QA 스택(vLLM GPU 0)에서 간소화 프롬프트로 같은 kor.mp4 턴 재실행, 품질/레이턴시 비교.

## 프로덕션 배치(미결, 사용자 결정)

| 안 | 위치 | 비고 |
|---|---|---|
| A | `signals_payload`에 `turnHandoff` 키 추가 (서버 측, 레코드에서 계산) | 파이프라인 무수정·소비자가 폴링으로 받음 — **추천** |
| B | SignalRecorder가 turn_end 시 `turn_handoff` 레코드 emit | 레코드 스트림에 남음(JSONL에도) |

어느 쪽이든 additive(기존 소비자 무영향). ai-engine은 `lastAnswer` 옆에 `analysisBlock`(=prompt_block)
한 필드만 받아 프롬프트에 끼우면 됨 — 프론트 중계 1줄 + `build_question_prompt` 1줄.

## 진행 메모 (2026-06-11 밤)
- PR #13(realtime, OpenAI Realtime sideband) 기준 **문장 레인 구현 착수** — GilJobE에
  `pipeline/sentences.py` + `SentenceSignal/Record` + 윈도워 외부 전사 모드. gemma 3s STT
  호출은 external 모드에서 제거(전사=Realtime 위임), PCM/프레임 버퍼는 측정용으로 유지.

## 열린 질문
1. `analysis.verbal`(윈도별 logic/structure/specificity)을 prompt_block에도 넣을지 — 현재는 머신 섹션만
   (concerns가 이미 내용 비평을 요약). 넣으면 +400자.
2. NV 레인 버그 해결 전까지 `nonverbal.windows=0` — 스키마는 대응 완료(섹션 생략), 버그는 별도 트랙.
3. 모순 플래그 확장(속도·음량·쉼·제스처)은 post-MVP #5(그라운딩 모순 자동 플래깅)와 합류.
