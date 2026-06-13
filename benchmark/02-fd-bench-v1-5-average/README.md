# FD-bench V1.5 Average

## 이것이 무엇인가

FD-bench V1.5는 full-duplex speech model이 overlap 상황을 어떻게 처리하는지 평가한다. 논문은 네 가지 overlap scenario를 제시한다.

- user interruption
- listener backchannel
- side conversation
- ambient/background speech

Thinking Machines 표의 `FD-bench V1.5 Average`는 이 overlap handling 품질을 평균한 interactivity quality 지표로 사용된다.

## 출처

- Paper: https://arxiv.org/abs/2507.23159
- Repo: https://github.com/DanielLin94144/Full-Duplex-Bench/tree/main/v1_v1.5
- Thinking Machines benchmark table: https://thinkingmachines.ai/blog/interaction-models/

## 데이터

공식 setup은 prerecorded audio를 full-duplex agent에 넣고, agent가 말하는 도중 들어오는 user interruption, listener backchannel, 주변 대화, 배경음에 대해 멈춰야 하는지, 계속 말해야 하는지, 자연스럽게 반응해야 하는지 측정한다.

repo는 inference output audio를 만들고, time-aligned transcript를 만든 뒤 task별 evaluation script로 평가하는 구조다.

## 공식 측정 방식

논문과 repo가 보는 축은 크게 다음이다.

- categorical dialogue behavior: 멈춤, 계속 말함, 수리 발화, backchannel 등 행동 분류
- stop latency: 멈춰야 할 때 얼마나 빨리 멈추는가
- response latency: 반응해야 할 때 얼마나 빨리 반응하는가
- prosodic adaptation: 겹침/방해 상황에서 prosody가 자연스러운가
- perceived speech quality: 사람이 듣기에 응답 품질이 어떤가

Thinking Machines의 표는 이 복수 지표를 평균 quality 형태로 요약한다.

## GilJob에서 측정 가능한가

라벨: `not-ready` 또는 `diagnostic-only`

GilJob의 메인 방향은 API-mediated OpenAI Realtime WebRTC audio path로 바뀌었지만, 제품 boundary가 아직 FD-bench V1.5식 overlap controller와 평가 event schema로 고정된 것은 아니다. 사용자 끼어들기 처리, side conversation 무시, listener backchannel 생성은 별도 product behavior로 정의되어야 한다.

따라서 공식 점수를 만드는 것은 부정확하다. 다만 다음처럼 일부 diagnostic만 만들 수 있다.

- background speech가 transcript에 섞이는 비율
- side conversation이 interview answer로 오인되는 비율
- user interruption audio가 들어왔을 때 analysis-engine stop/final transcript가 깨지는지
- 모델 output audio 중 사용자 마이크 입력이 들어올 때 session state가 안전하게 유지되는지

## GilJob용 adapter 설계

정식 벤치마크를 목표로 하려면 다음 boundary가 필요하다.

1. OpenAI Realtime session 또는 동등 full-duplex adapter에 user/output audio overlap을 주입한다.
2. agent가 말하는 중 incoming speech를 처리할 수 있는 product controller를 둔다.
3. stop/continue/backchannel behavior를 model/session event로 기록한다.
4. output audio 또는 text delta에 timestamp를 붙여 stop latency와 response latency를 계산한다.

현재는 이 controller/evaluation schema가 없으므로 `GilJob v2 Realtime product path`에는 official-compatible 행을 만들지 않는다.

## 다음 준비 작업

1. 이 벤치마크는 후순위로 둔다.
2. 먼저 FD-bench V1 latency로 Realtime gate와 첫 응답 delta를 측정한다.
3. overlap behavior를 제품 요구사항으로 고정할 때 다시 target으로 올린다.

## 주의점

V1.5는 "면접 질문 품질"보다 "겹쳐 말하는 실시간 대화 행동"을 본다. GilJob의 현재 핵심 가치인 structured interview flow와는 직접 연결성이 낮다.
