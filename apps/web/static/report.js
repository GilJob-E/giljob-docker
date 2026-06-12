// report.js — 면접 리포트 페이지의 "동적 데이터 로더"
//
// interview-report.html 은 화면의 '뼈대'와 '예시값'만 가지고 있습니다.
// 이 스크립트가 페이지가 열린 뒤 실행되어, 서버 API에서 '진짜 데이터'를 받아
// 그 자리에 채워 넣습니다. (HTML=뼈대, report.js=일꾼, API=데이터 창고)
//
// 핵심 안전 규칙:
//  - 텍스트는 항상 textContent 로만 넣습니다(innerHTML 금지 → 스크립트 주입 방지).
//  - API가 아직 없거나 실패하면 예시값을 그대로 둡니다(graceful fallback).

const REPORT_API_BASE = "/api/interviews";

// 1) 지금 보고 있는 페이지 주소에서 interviewId 를 뽑아냅니다.
//    예: /interviews/local-demo/report  →  "local-demo"
function interviewIdFromPath() {
  const match = window.location.pathname.match(/\/interviews\/([^/]+)\/report/);
  return match ? decodeURIComponent(match[1]) : null;
}

// 2) 리포트 토큰(열람 권한). 보안상 주소(URL)에 넣지 않으므로,
//    실제 서비스에서는 별도 방법으로 주입됩니다. 지금은 없으면 그냥 생략합니다.
function reportToken() {
  return window.__REPORT_TOKEN__ || null;
}

// 3) 서버에 "이 면접의 리포트 데이터를 줘" 라고 요청해 JSON 을 받습니다.
//    fetch = 브라우저가 서버에 보내는 비동기 요청. await = 응답이 올 때까지 기다림.
async function fetchReport(interviewId) {
  const headers = {};
  const token = reportToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const response = await fetch(
    `${REPORT_API_BASE}/${encodeURIComponent(interviewId)}/report`,
    { headers },
  );
  if (!response.ok) {
    throw new Error(`report HTTP ${response.status}`);
  }
  return response.json(); // 응답 본문(JSON 문자열)을 JS 객체로 변환
}

// ── DOM 만들기 도우미 ───────────────────────────────────────────────
// DOM = 화면을 이루는 요소 트리. 아래 함수로 요소를 안전하게 만들어 끼웁니다.
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text != null) {
    node.textContent = text; // 항상 textContent (innerHTML 아님)
  }
  return node;
}

// 4) 숫자 지표 타일 하나: <div class="metric"><dt>라벨</dt><dd>값<span>단위</span></dd></div>
function metricTile(label, value, unit) {
  const wrap = el("div", "metric");
  wrap.appendChild(el("dt", null, label));
  const dd = el("dd", null, String(value));
  if (unit) {
    dd.appendChild(el("span", null, unit));
  }
  wrap.appendChild(dd);
  return wrap;
}

// 5) 한 턴(질문 + 답변 + 접이식 분석)을 통째로 만듭니다.
function turnItem(turn, index) {
  const li = el("li", "turn-item");
  li.appendChild(el("div", "turn-index", `Q${turn.turnId ?? index + 1}`));

  const body = el("div", "turn-body");
  body.appendChild(el("p", "turn-q", turn.question || "질문 정보 없음"));
  body.appendChild(el("p", "turn-a", turn.answer || "(전사 없음)"));

  // 접이식 분석 영역 <details>
  const details = el("details", "turn-eval");
  details.appendChild(el("summary", "turn-eval-toggle", "답변 분석 보기"));
  const content = el("div", "turn-eval-content");

  // (1) 피드백 블록
  const feedback = turn.feedback || {};
  const fbBlock = el("div", "eval-block");
  fbBlock.appendChild(el("p", "eval-block-title", "피드백"));
  const observations = (feedback.keyObservations || []).join(" ");
  if (observations) {
    fbBlock.appendChild(el("p", "turn-eval-summary", observations));
  }
  if (Array.isArray(feedback.critique) && feedback.critique.length > 0) {
    const tags = el("ul", "turn-eval-tags");
    for (const item of feedback.critique) {
      tags.appendChild(el("li", null, item));
    }
    fbBlock.appendChild(tags);
  }
  content.appendChild(fbBlock);

  // (2) 비언어 지표 블록
  const metrics = turn.metrics || {};
  const vocal = metrics.vocal || {};
  const visual = metrics.visual || {};
  // coverage.visualMeasurable 이 false 면 시각 지표는 '측정 불가'로 처리(가짜 수치 방지)
  const visualMeasurable = metrics.coverage
    ? metrics.coverage.visualMeasurable !== false
    : true;

  const metricBlock = el("div", "eval-block");
  metricBlock.appendChild(el("p", "eval-block-title", "비언어 지표"));
  const grid = el("dl", "metric-grid");

  if (vocal.speechRateSylPerSec != null) {
    grid.appendChild(metricTile("말 속도", vocal.speechRateSylPerSec, "음절/초"));
  }
  if (vocal.pitchMeanHz != null) {
    grid.appendChild(metricTile("평균 음높이", Math.round(vocal.pitchMeanHz), "Hz"));
  }
  if (vocal.pauseCount != null) {
    grid.appendChild(metricTile("긴 휴지", vocal.pauseCount, "회"));
  }
  if (visualMeasurable) {
    if (visual.smileMean != null) {
      grid.appendChild(metricTile("미소", Math.round(visual.smileMean * 100), "%"));
    }
    if (visual.gazeOffMean != null) {
      grid.appendChild(metricTile("시선 이탈", Math.round(visual.gazeOffMean * 100), "%"));
    }
    if (visual.blinkCount != null) {
      grid.appendChild(metricTile("눈 깜빡임", visual.blinkCount, "회"));
    }
  }
  metricBlock.appendChild(grid);
  if (!visualMeasurable) {
    metricBlock.appendChild(
      el("p", "eval-unmeasured", "이 구간은 얼굴이 충분히 잡히지 않아 시각 지표는 측정되지 않았습니다."),
    );
  }
  content.appendChild(metricBlock);

  details.appendChild(content);
  body.appendChild(details);
  li.appendChild(body);
  return li;
}

// ── 집계(평균/합계) 도우미 ──────────────────────────────────────────
// 여러 턴의 숫자를 모아 평균/합계를 냅니다. 값이 없는 턴은 자동으로 빠집니다.
function collect(list, pick) {
  return list.map(pick).filter((n) => typeof n === "number" && !Number.isNaN(n));
}
function mean(nums) {
  return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null;
}
function total(nums) {
  return nums.length ? nums.reduce((a, b) => a + b, 0) : null;
}

// 종합 카드의 숫자 칸 하나를 갱신: <dd>값<span>단위</span></dd>
function setMetric(id, value, unit) {
  const dd = document.getElementById(id);
  if (!dd) {
    return;
  }
  if (value == null) {
    dd.textContent = "—"; // 측정값이 없으면 대시
    return;
  }
  dd.textContent = String(value);
  if (unit) {
    dd.appendChild(el("span", null, unit));
  }
}

// 7) 종합(평균 비언어 지표) 카드 채우기 — 모든 턴의 metrics 를 모아 평균/합계 계산
function renderSummary(turns) {
  const vocal = turns.map((t) => (t.metrics || {}).vocal || {});
  // 시각 지표는 '측정 가능'한 턴만 평균에 포함(가짜 수치 방지)
  const measurableTurns = turns.filter((t) => {
    const coverage = (t.metrics || {}).coverage;
    return coverage ? coverage.visualMeasurable !== false : true;
  });
  const visual = measurableTurns.map((t) => (t.metrics || {}).visual || {});

  const rate = mean(collect(vocal, (v) => v.speechRateSylPerSec));
  const pitch = mean(collect(vocal, (v) => v.pitchMeanHz));
  const pause = total(collect(vocal, (v) => v.pauseCount));
  const smile = mean(collect(visual, (v) => v.smileMean));
  const gaze = mean(collect(visual, (v) => v.gazeOffMean));
  const blink = total(collect(visual, (v) => v.blinkCount));

  setMetric("avg-rate", rate == null ? null : Math.round(rate * 10) / 10, "음절/초");
  setMetric("avg-pitch", pitch == null ? null : Math.round(pitch), "Hz");
  setMetric("sum-pause", pause, "회");
  setMetric("avg-smile", smile == null ? null : Math.round(smile * 100), "%");
  setMetric("avg-gaze", gaze == null ? null : Math.round(gaze * 100), "%");
  setMetric("sum-blink", blink, "회");

  const coverageEl = document.getElementById("summary-coverage");
  if (coverageEl) {
    coverageEl.textContent =
      `시각 지표는 ${turns.length}개 답변 중 ${measurableTurns.length}개에서 측정되었습니다.`;
  }
}

// 8) 받은 리포트(JSON)로 화면을 채웁니다.
function renderReport(report) {
  // 헤더 메타값
  const dateEl = document.getElementById("meta-date");
  if (dateEl && typeof report.generatedAt === "string") {
    dateEl.textContent = report.generatedAt.slice(0, 10); // "2026-06-11"
  }
  const turnsEl = document.getElementById("meta-turns");
  if (turnsEl && report.turnCount != null) {
    turnsEl.textContent = `${report.turnCount}개`;
  }

  if (Array.isArray(report.turns)) {
    // 종합(평균 비언어 지표) 카드
    renderSummary(report.turns);

    // 다이얼로그: 예시 턴들을 지우고, 실제 턴으로 다시 그립니다.
    const list = document.querySelector(".turn-list");
    if (list) {
      const items = report.turns.map((turn, i) => turnItem(turn, i));
      list.replaceChildren(...items); // 통째 교체 (innerHTML 안 씀)
    }
  }
}

// 9) 리포트를 받되, 아직 분석이 덜 끝났으면(complete=false) 잠깐 기다렸다 재시도.
//    면접 직후 열면 마지막 턴 지표가 아직 안 들어왔을 수 있어, 짧게 몇 번 다시 받습니다.
async function loadReportWithRetry(interviewId, attempts = 4, delayMs = 800) {
  let report = null;
  for (let i = 0; i < attempts; i += 1) {
    report = await fetchReport(interviewId);
    if (report.complete || i === attempts - 1) {
      return report;
    }
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
  return report;
}

// 10) 진입점: 페이지가 열리면 이 함수가 실행됩니다.
async function init() {
  const interviewId = interviewIdFromPath();
  if (!interviewId) {
    return; // 리포트 라우트가 아니면 아무것도 하지 않음
  }
  try {
    const report = await loadReportWithRetry(interviewId);
    renderReport(report); // 성공(또는 마지막 시도) → 받은 데이터로 교체
  } catch (error) {
    // 실패(API 미구현 / 네트워크 / 권한 없음) → 예시 화면을 그대로 유지
    console.info(`리포트 데이터를 불러오지 못해 예시 화면을 유지합니다: ${error.message}`);
  }
}

init();
