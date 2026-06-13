# eval A/B — 16s 벽시계+풀 축(A) vs 문장 정렬+slim 축(B) (2026-06-12)

A = `../2026-06-12-evalab-a/` (배포 상태 그대로), B = 이 폴더 (핫패치: `GILJOBE_EVAL_GRID=sentence`
+ `GILJOBE_EVAL_AXES=slim` 기본값 플립). 동일 조건: fakecam 퍼블리시, kor 클립, 같은 sideband
이벤트, 같은 gemma. 런 후 컨테이너는 기본값(wall/full) 코드로 원복함.

## 수치

| 지표 | A (16s wall, full) | B (문장 정렬, slim) |
|---|---|---|
| eval 윈도우 | [0,16), [16,32) | [0,14.57)=문장1~4 count 트리거, [14.57,29.57)=문장5~6 span 트리거 |
| **eval 꼬리(윈도 끝→레코드)** | **8.52 / 8.59s** | **7.56 / 5.41s** (2번째 윈도 −37%) |
| vocal/visual 텍스트 축 | 있음 | `{}` (의도대로 제거) |
| stop→turn_end | 1.24s | 1.35s (동등) |
| sentence 레인 | 8문장, visual 8/8 | 8문장, visual 8/8 |

B의 꼬리엔 "윈도 미디어상 끝→completed 이벤트 도착"(~0.6s)이 포함돼 있어 순수 추론 단축은
표보다 크다. 1번째 윈도(7.56s)는 nv 4건과 gemma 동시 경합 구간이라 보수적 수치.

## 품질 관찰 (B)

- **verbal 3축이 A보다 눈에 띄게 깊어짐** — 출력 예산이 전달력 축에서 내용 비평으로 이동
  (logic/structure/specificity가 문장 수준으로 구체적).
- **key_observations가 실측 인용형으로 변함**: "짧은 휴지 16회", "미소 평균 0.159", "후반부 음량
  감소 추세" — 측정치와 일치할 때만 전달력 언급(프롬프트 의도 그대로).
- critique의 전달력 언급 1건도 실측 근거("음성 측정치상 후반부 음량 감소") — 모순 상투구 없음.
- **잔존 문제 2건**:
  1. compact tail(EVAL_TAIL_SYSTEM, 이번 A/B 미변경)은 여전히 "억양 변화가 단조로운 편" 상투구
     → tail 프롬프트에도 같은 처치 필요(후속).
  2. B 2번째 윈도 verbal에 수치 오인 ("26% 단축" — 실제 발화는 6%, "대상도 수당" — 실제 "대상도
     받을"). gemma 오디오 청해 노이즈로 보이며 slim 귀속 불가(단일 표본) — 재현 관찰 필요.

## 판정 (제안)

문장 정렬 + slim 축은 **레이턴시·그라운딩·비평 깊이 모두 개선, 회귀 없음** (단일 클립 1런 기준).
프로덕션 편입은 사용자 결정 대기 — 편입 시 compose에 `GILJOBE_EVAL_GRID` / `GILJOBE_EVAL_AXES`
배선 + tail 프롬프트 동일 처치 권장.

## 코드

GilJobE 워킹트리(main=dae5191 위) — `windowing.py`(SENT_EVAL_* 트리거, 가변 폭 covered_until),
`critic.py`(EVAL_SYSTEM_SLIM, eval_axes), `app.py`/`__main__.py`(env 배선). 기본값은
wall/full(무변경). 테스트: windowing 트리거/연쇄 + critic 프롬프트 선택 가드, 전 스위트 157 passed.
