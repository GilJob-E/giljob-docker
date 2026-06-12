# MMM 보완 설계 — 7개 벤치마크 매핑

작성: 2026-06-12. 입력: `dataset_characteristics.md` + 7개 벤치 README + 소넷 조사 7건.
기준: MMM(analysis-engine/GilJobE 분석 경로) 관점에서 각 벤치가 요구하는 능력과 현 갭.

## 분류 원칙

분석 레인의 철칙 두 개가 무엇을 "MMM 보완"으로 볼지 가른다.
1. **LLM 호출 0** — `build_turn_handoff`는 폴링마다 lazy 계산되는 순수 파이썬. 자연어 이해가
   필요한 작업(제약 추출·모순 판단·내용 reasoning)은 분석 레인 본업이 아니라 소비자 LLM 몫.
2. **실시간성 ★1순위** — 측정은 발화 중, 판단은 소비자. 게이트 지연이 곧 제품 레이턴시.

따라서 세 영역으로 나눈다:
- **A. 분석 레인 직접(LLM 0)** — 보완하면 곧 벤치 신호. 이번 워크스트림의 본체.
- **B. 분석 출력(fragment) 계약** — fragment의 안전·형식이 분석 레인 책임.
- **C. 소비자 LLM / 모델 영역** — 분석 레인은 재료만 운반, 보완 주체는 다른 레이어.

## 매핑 표

| # | 벤치 | 측정 대상 | MMM 관련 | 분석 레인 보완 포인트 | 영역 |
|---|---|---|---|---|---|
| 1 | FD-Bench V1 latency | 발화 종료→첫 응답 지연 | ★높음 | `full_mmm_ready` 게이트 = MMM 내부 지연. 단계별 타임스탬프 노출로 병목 pin-point | A |
| 4 | QIVD | video QA 정확도+timing | 중(부분) | 손가락 95·제스처 47·자세/동작 일부 = hands/pose 레인 직접. 나머지 ~80%는 VLM | A(부분)+C |
| 5 | Audio MultiChallenge | 기억·지시유지·자기일관 | 중 | 턴에서 명시된 검증가능 사실/제약을 구조 추출해 운반(누적·판단은 소비자) | C 주, A 보조 |
| 6 | BigBench Audio | 오디오 reasoning 정확도 | 낮음 | 전사 충실도 검증·무응답 분리만 | C |
| 7 | IFEval VoiceBench | spoken 지시 따르기 | 중 | fragment 주입이 instruction following 해치는지 A/B + 오디오이해/위반 분리 | B |
| 8 | IFEval Text | text 지시 따르기 | 중 | fragment 형식 계약을 verifiable rule로 self-check, 주입 on/off A/B | B |
| 9 | HarmBench | 거부율/공격성공 | 중 | 위험 발화의 사이드밴드→fragment 전파 차단 계약, GilJob-safety set | B |

## 우선순위 (분석 레인 보완 임팩트 순)

1. **QIVD 비전 subset 실측·보완** (A) — 방금 만든 hands 레인의 직접 연속. 손가락 95개로
   레인 정확도를 벤치 척도로 실측 → 갭 → 보완. 비전 레인이 곧 벤치 신호가 되는 유일 경로.
2. **FD-Bench V1 단계별 레이턴시 계측** (A) — 실시간성 ★1순위 직결. turn_handoff 빌드·
   fragment 서빙 타임스탬프를 turn-results에 노출 → mmm_ready_latency 분해.
3. **fragment 계약 verifiable checker + redaction 강화** (B) — IFEval(형식)+HarmBench(안전)
   동시 커버. 개행/길이/금칙어/수치-시간 사이드채널을 IFEval식 rule로 self-check.
4. **Audio MC 사실/제약 추출 슬롯** (C/A 경계) — 턴에서 명시 수치(경력·기대연봉 등)를
   순수 규칙으로 추출 운반. 누적·모순 판단은 소비자. LLM-0 가능 범위만.
5. **BigBench/VoiceBench audio adapter** (C) — Realtime/ASR row 분리. 모델·제품 영역, 후속.

## QIVD 비전 subset 실측 대상(이번 단위)

`labels.json` 2,900개 중 hands/pose 레인이 LLM 0으로 답 가능한 후보:
- **손가락 카운팅 95개** ("How many fingers…") — hands 레인 손가락 셈 직접
- **손 제스처 47개** (waving/thumbs up/peace sign/calling) — 펼친 손가락 패턴 분류
- 자세/방향·단순 동작 일부(action attributes/detection) — pose 레인, 정확도 낮을 것

실측 → 정확도/혼동 → 갭(예: 가림형 손가락, 동적 제스처 분류 부재) → 레인 보완.
나머지 ~80%(객체 인식·OCR·장면)는 VLM offline adapter 영역으로 분리(이 워크스트림 밖).
