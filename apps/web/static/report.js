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
const reportPagerState = {
  groupIndex: 0,
  turns: [],
  groups: [],
};

// API를 못 받았을 때(개발 중·권한 없음 등) 차트·애니메이션을 보여주기 위한 예시 데이터.
const PLACEHOLDER_REPORT = {
  generatedAt: "2026-06-11T00:00:00Z",
  turnCount: 7,
  complete: true,
  turns: [
    {
      turnId: 1,
      topic: "지원 동기",
      topicSource: "fallback_transcript_only",
      question: "간단한 자기소개와 지원 동기를 말씀해 주세요.",
      answer: "안녕하세요. 4년 차 백엔드 엔지니어 김지원입니다. 결제 시스템의 정합성 문제를 다루며 분산 트랜잭션에 관심을 갖게 됐고, 이 팀의 도메인이 그 경험과 맞닿아 지원했습니다.",
      feedback: { keyObservations: ["지원 동기와 경험의 연결이 명확합니다."], critique: ["도입부 긴장 신호는 낮은 편입니다."] },
      metrics: { vocal: { speechRateSylPerSec: 5.7, pitchMeanHz: 237, pauseCount: 0 }, visual: { smileMean: 0.19, gazeOffMean: 0.26, blinkCount: 0 }, coverage: { visualMeasurable: true } },
    },
    {
      turnId: 2,
      topic: "지원 동기",
      topicSource: "fallback_transcript_only",
      question: "GilJob 팀에서 특히 기여하고 싶은 영역은 무엇인가요?",
      answer: "면접 평가가 주관적으로 흘러가지 않도록 데이터 기반 근거를 남기는 영역에 기여하고 싶습니다. 백엔드 안정성과 리포트 신뢰도를 함께 챙기는 역할이 제 강점과 잘 맞습니다.",
      feedback: { keyObservations: ["제품 방향과 본인의 역할을 구체적으로 연결했습니다."], critique: ["기여 영역을 하나로 좁혀 말해 설득력이 높습니다."] },
      metrics: { vocal: { speechRateSylPerSec: 5.4, pitchMeanHz: 229, pauseCount: 1 }, visual: { smileMean: 0.24, gazeOffMean: 0.22, blinkCount: 1 }, coverage: { visualMeasurable: true } },
    },
    {
      turnId: 3,
      topic: "기술 문제 해결",
      topicSource: "fallback_transcript_only",
      question: "최근 해결한 가장 어려운 기술 문제는 무엇이었나요?",
      answer: "대량 정산 배치에서 중복 지급이 간헐적으로 발생했습니다. 멱등 키와 상태 머신을 도입해 재처리 안전성을 확보했고, 사고율을 0으로 떨어뜨렸습니다.",
      feedback: { keyObservations: ["문제–원인–해결 흐름이 분명합니다."], critique: ["정량 성과(사고율 0)를 제시했습니다."] },
      metrics: { vocal: { speechRateSylPerSec: 5.9, pitchMeanHz: 250, pauseCount: 0 }, visual: { smileMean: 0.20, gazeOffMean: 0.37, blinkCount: 1 }, coverage: { visualMeasurable: true } },
    },
    {
      turnId: 4,
      topic: "기술 문제 해결",
      topicSource: "fallback_transcript_only",
      question: "그 문제의 원인을 어떻게 좁혀 갔나요?",
      answer: "처음에는 배치 재시도 로직을 의심했지만, 지급 요청 로그와 계좌 상태 변경 로그를 같은 타임라인에 올려 보니 외부 응답 지연 뒤 중복 커밋이 발생한다는 점을 확인했습니다.",
      feedback: { keyObservations: ["가설을 세우고 로그로 좁혀 간 과정이 드러납니다."], critique: ["관찰한 증거와 판단 근거를 함께 말했습니다."] },
      metrics: { vocal: { speechRateSylPerSec: 5.1, pitchMeanHz: 221, pauseCount: 2 }, visual: { smileMean: 0.14, gazeOffMean: 0.31, blinkCount: 2 }, coverage: { visualMeasurable: true } },
    },
    {
      turnId: 5,
      topic: "기술 문제 해결",
      topicSource: "fallback_transcript_only",
      question: "같은 문제가 다시 생기지 않도록 어떤 장치를 남겼나요?",
      answer: "멱등 키 외에도 상태 전이별 알림과 대시보드를 추가했습니다. 장애가 재현되면 어떤 단계에서 멈췄는지 바로 볼 수 있게 해 운영 대응 시간을 줄였습니다.",
      feedback: { keyObservations: ["해결 이후의 예방 장치까지 설명했습니다."], critique: ["운영 관점의 후속 조치가 좋습니다."] },
      metrics: { vocal: { speechRateSylPerSec: 4.8, pitchMeanHz: 214, pauseCount: 1 }, visual: { smileMean: 0.17, gazeOffMean: 0.28, blinkCount: 1 }, coverage: { visualMeasurable: true } },
    },
    {
      turnId: 6,
      topic: "협업 방식",
      topicSource: "fallback_transcript_only",
      question: "의견이 다른 동료와 협업한 경험을 말씀해 주세요.",
      answer: "스키마 설계에서 이견이 있었는데, 양쪽 안의 트레이드오프를 표로 정리해 함께 검토했습니다. 결국 상대 안을 일부 수용하는 절충안으로 합의했습니다.",
      feedback: { keyObservations: ["상대 관점을 반영한 협업 태도가 드러납니다."], critique: ["갈등 해소 과정이 구체적입니다."] },
      metrics: { vocal: { speechRateSylPerSec: 4.2, pitchMeanHz: 192, pauseCount: 1 }, coverage: { visualMeasurable: false } },
    },
    {
      turnId: 7,
      topic: "협업 방식",
      topicSource: "fallback_transcript_only",
      question: "그 과정에서 본인이 양보하지 않은 기준은 무엇이었나요?",
      answer: "팀 합의는 유연하게 가져가되, 장애 시 복구 가능한 구조와 데이터 추적 가능성은 꼭 지켜야 한다고 봤습니다. 그래서 절충안에도 감사 로그와 롤백 경로는 남겼습니다.",
      feedback: { keyObservations: ["협업 속에서도 지켜야 할 기술 기준을 설명했습니다."], critique: ["양보와 원칙의 균형이 비교적 선명합니다."] },
      metrics: { vocal: { speechRateSylPerSec: 4.6, pitchMeanHz: 201, pauseCount: 1 }, visual: { smileMean: 0.12, gazeOffMean: 0.34, blinkCount: 2 }, coverage: { visualMeasurable: true } },
    },
  ],
};

// 1) 지금 보고 있는 페이지 주소에서 interviewId 를 뽑아냅니다.
//    예: /interviews/local-demo/report  →  "local-demo"
function interviewIdFromPath() {
  const match = window.location.pathname.match(/\/interviews\/([^/]+)\/report/);
  // Fall back to a default id so static preview paths (e.g. /interview-report.html)
  // still trigger a fetch; if the API is absent the page shows placeholder data.
  return match ? decodeURIComponent(match[1]) : "local-demo";
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

// ── 애니메이션 · 차트 도우미 ─────────────────────────────────────────
const SVG_NS = "http://www.w3.org/2000/svg";

function prefersReducedMotion() {
  return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}
function easeOutCubic(p) {
  return 1 - Math.pow(1 - p, 3);
}
function svgEl(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    node.setAttribute(name, String(value));
  }
  return node;
}

// 종합 카드 숫자 칸을 0에서 목표값까지 '차오르게' 갱신.
function animateMetric(id, target, { decimals = 0, suffix = "" } = {}) {
  const dd = document.getElementById(id);
  if (!dd) {
    return;
  }
  if (target == null) {
    dd.textContent = "—";
    return;
  }
  const apply = (num) => {
    dd.textContent = decimals > 0 ? num.toFixed(decimals) : String(Math.round(num));
    if (suffix) {
      dd.appendChild(el("span", null, suffix));
    }
  };
  if (prefersReducedMotion()) {
    apply(target);
    return;
  }
  const duration = 900;
  const start = performance.now();
  function frame(now) {
    const progress = Math.min(1, (now - start) / duration);
    apply(target * easeOutCubic(progress));
    if (progress < 1) {
      requestAnimationFrame(frame);
    }
  }
  requestAnimationFrame(frame);
}

// 차트에 그릴 지표들. 단위가 제각각이라 지표별로 0~1 정규화해 그립니다.
function trendVisual(metrics, key) {
  const measurable = metrics.coverage ? metrics.coverage.visualMeasurable !== false : true;
  return measurable && metrics.visual ? metrics.visual[key] : undefined;
}
const TREND_FEATURES = [
  { key: "rate", label: "말 속도", color: "#3b82f6", get: (m) => (m.vocal || {}).speechRateSylPerSec },
  { key: "pitch", label: "음높이", color: "#8b5cf6", get: (m) => (m.vocal || {}).pitchMeanHz },
  { key: "pause", label: "긴 휴지", color: "#10b981", get: (m) => (m.vocal || {}).pauseCount },
  { key: "smile", label: "미소", color: "#f59e0b", get: (m) => trendVisual(m, "smileMean") },
  { key: "gaze", label: "시선 이탈", color: "#ef4444", get: (m) => trendVisual(m, "gazeOffMean") },
  { key: "blink", label: "눈 깜빡임", color: "#64748b", get: (m) => trendVisual(m, "blinkCount") },
];

// 범례 클릭 시 해당 지표의 선·점 표시/숨김 (기본 전부 켜짐).
function setFeatureVisible(svg, key, visible) {
  svg.querySelectorAll(`[data-feature="${key}"]`).forEach((node) => {
    node.style.display = visible ? "" : "none";
  });
}

function fallbackTopicForPosition(position, total) {
  const labels = [
    "기본 역량 확인",
    "경험 회고와 성장 방향",
    "심화 역량 확인",
    "추가 응답 확인",
  ];
  if (total <= 0) {
    return labels[0];
  }
  const groupCount = Math.max(1, Math.ceil(total / 3));
  let remaining = total;
  let cursor = 1;
  for (let groupIndex = 0; groupIndex < groupCount; groupIndex += 1) {
    const groupsLeft = groupCount - groupIndex;
    const size = groupsLeft > 1
      ? Math.min(3, remaining - 2 * (groupsLeft - 1))
      : remaining;
    if (cursor <= position && position < cursor + size) {
      return labels[groupIndex] || `추가 응답 확인 ${groupIndex + 1}`;
    }
    cursor += size;
    remaining -= size;
  }
  return labels[labels.length - 1];
}

function topicLooksMissing(topic, topicSource) {
  return !topic || (topic === "미분류" && (!topicSource || topicSource === "fallback_transcript_only"));
}

function normalizeTurnTopic(turn, index = 0, total = 1) {
  const topicSource = turn.topicSource || "fallback_transcript_only";
  if (!topicLooksMissing(turn.topic, topicSource)) {
    return { ...turn, topic: turn.topic, topicSource };
  }
  return {
    ...turn,
    topic: fallbackTopicForPosition(index + 1, total),
    topicSource: "fallback_demo_group",
  };
}

function buildTopicGroups(turns) {
  const groups = [];
  for (let index = 0; index < turns.length; index += 1) {
    const rawTurn = turns[index];
    const turn = normalizeTurnTopic(rawTurn, index, turns.length);
    const topic = turn.topic;
    const topicSource = turn.topicSource;
    const latest = groups[groups.length - 1];
    if (!latest || latest.topic !== topic) {
      groups.push({
        groupId: `topic_${groups.length + 1}`,
        topic,
        topicSource,
        startTurnId: turn.turnId,
        endTurnId: turn.turnId,
        turns: [turn],
      });
    } else {
      latest.endTurnId = turn.turnId;
      latest.turns.push(turn);
    }
  }
  return groups;
}

function normalizeTopicGroups(report) {
  const reportTurns = Array.isArray(report.turns) ? report.turns : [];
  const rebuiltGroups = buildTopicGroups(reportTurns);
  if (Array.isArray(report.topicGroups) && report.topicGroups.length > 0) {
    const groups = report.topicGroups
      .map((group) => ({
        groupId: group.groupId,
        topic: group.topic || "미분류",
        topicSource: group.topicSource || "fallback_transcript_only",
        startTurnId: group.startTurnId,
        endTurnId: group.endTurnId,
        turns: Array.isArray(group.turns)
          ? group.turns.map((turn, index) => normalizeTurnTopic(turn, index, group.turns.length))
          : [],
      }))
      .filter((group) => group.turns.length > 0);
    const singleMissingGroup = groups.length === 1 && topicLooksMissing(groups[0].topic, groups[0].topicSource);
    if (singleMissingGroup && rebuiltGroups.length > 1) {
      return rebuiltGroups;
    }
    if (groups.length > 0) {
      return groups;
    }
  }
  return rebuiltGroups;
}

function currentGroup() {
  return reportPagerState.groups[reportPagerState.groupIndex] || {
    topic: "미분류",
    startTurnId: null,
    endTurnId: null,
    turns: reportPagerState.turns,
  };
}

function groupStatusText() {
  if (reportPagerState.groups.length === 0) {
    return "표시할 주제 없음";
  }
  const group = currentGroup();
  const range = group.startTurnId === group.endTurnId
    ? `Q${group.startTurnId}`
    : `Q${group.startTurnId}–Q${group.endTurnId}`;
  return `${reportPagerState.groupIndex + 1}/${reportPagerState.groups.length} · ${group.topic} · ${range}`;
}

function updateTopicPagerControls() {
  const total = reportPagerState.groups.length;
  for (const kind of ["trend", "dialog"]) {
    const prev = document.getElementById(`${kind}-prev`);
    const next = document.getElementById(`${kind}-next`);
    const status = document.getElementById(`${kind}-page-status`);
    if (prev) {
      prev.disabled = total <= 1 || reportPagerState.groupIndex <= 0;
    }
    if (next) {
      next.disabled = total <= 1 || reportPagerState.groupIndex >= total - 1;
    }
    if (status) {
      status.textContent = groupStatusText();
    }
  }
}

function renderTopicGroup() {
  const group = currentGroup();
  renderTrendChart(group.turns);
  const list = document.querySelector(".turn-list");
  if (list) {
    const items = group.turns.map((turn, i) => turnItem(turn, i));
    list.replaceChildren(...items); // 통째 교체 (innerHTML 안 씀)
  }
  updateTopicPagerControls();
}

function wireTopicPager(kind) {
  const prev = document.getElementById(`${kind}-prev`);
  const next = document.getElementById(`${kind}-next`);
  prev?.addEventListener("click", () => {
    reportPagerState.groupIndex = Math.max(0, reportPagerState.groupIndex - 1);
    renderTopicGroup();
  });
  next?.addEventListener("click", () => {
    reportPagerState.groupIndex = Math.min(reportPagerState.groups.length - 1, reportPagerState.groupIndex + 1);
    renderTopicGroup();
  });
}

// 선이 X축을 따라 그려지는 애니메이션 (stroke-dashoffset).
function animateDraw(poly, order) {
  let length = 0;
  try {
    length = poly.getTotalLength();
  } catch (error) {
    length = 0;
  }
  if (!length || prefersReducedMotion()) {
    return;
  }
  poly.style.strokeDasharray = String(length);
  poly.style.strokeDashoffset = String(length);
  poly.getBoundingClientRect(); // 강제 리플로우 후 트랜지션 시작
  poly.style.transition = `stroke-dashoffset 900ms ease ${order * 150}ms`;
  requestAnimationFrame(() => {
    poly.style.strokeDashoffset = "0";
  });
}

// 턴(X축)별 각 지표(Y축) 꺾은선 그래프를 그립니다.
function renderTrendChart(turns) {
  const chart = document.getElementById("trend-chart");
  const legend = document.getElementById("trend-legend");
  if (!chart) {
    return;
  }
  chart.replaceChildren();
  if (legend) {
    legend.replaceChildren();
  }
  const n = turns.length;
  if (n < 1) {
    return;
  }

  const W = 640, H = 240, padL = 12, padR = 12, padT = 16, padB = 28;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const xFor = (i) => (n === 1 ? W / 2 : padL + (i / (n - 1)) * plotW);
  const yFor = (norm) => padT + (1 - norm) * plotH;

  const svg = svgEl("svg", {
    viewBox: `0 0 ${W} ${H}`, class: "trend-svg", role: "img",
    "aria-label": "턴별 비언어 지표 추이",
  });
  for (const gridY of [0, 0.5, 1]) {
    svg.appendChild(svgEl("line", { x1: padL, y1: yFor(gridY), x2: W - padR, y2: yFor(gridY), class: "trend-grid" }));
  }
  for (let i = 0; i < n; i += 1) {
    const label = svgEl("text", { x: xFor(i), y: H - 8, class: "trend-xlabel", "text-anchor": "middle" });
    label.textContent = `Q${turns[i].turnId ?? i + 1}`;
    svg.appendChild(label);
  }

  let drawn = 0;
  for (const feature of TREND_FEATURES) {
    const points = [];
    for (let i = 0; i < n; i += 1) {
      const value = feature.get(turns[i].metrics || {});
      if (typeof value === "number" && !Number.isNaN(value)) {
        points.push({ i, value });
      }
    }
    if (points.length < 1) {
      continue;
    }
    const values = points.map((p) => p.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const norm = (v) => (max === min ? 0.5 : (v - min) / (max - min));
    const coords = points.map((p) => [xFor(p.i), yFor(norm(p.value))]);

    if (coords.length >= 2) {
      svg.appendChild(svgEl("polyline", {
        points: coords.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" "),
        class: "trend-line", fill: "none", stroke: feature.color, "data-feature": feature.key,
      }));
    }
    for (const [x, y] of coords) {
      svg.appendChild(svgEl("circle", {
        cx: x.toFixed(1), cy: y.toFixed(1), r: 2.6, class: "trend-dot", fill: feature.color, "data-feature": feature.key,
      }));
    }
    if (legend) {
      const item = el("li", "trend-legend-item");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "trend-legend-toggle";
      button.setAttribute("aria-pressed", "true"); // 기본 켜짐
      const swatch = el("span", "trend-swatch");
      swatch.style.background = feature.color;
      button.appendChild(swatch);
      button.appendChild(document.createTextNode(feature.label));
      button.addEventListener("click", () => {
        const next = button.getAttribute("aria-pressed") !== "true";
        button.setAttribute("aria-pressed", String(next));
        button.classList.toggle("is-off", !next);
        setFeatureVisible(svg, feature.key, next);
      });
      item.appendChild(button);
      legend.appendChild(item);
    }
    drawn += 1;
  }

  chart.appendChild(svg);
  if (drawn === 0) {
    chart.appendChild(el("p", "trend-empty", "표시할 비언어 지표 데이터가 아직 없습니다."));
    return;
  }
  // SVG가 DOM에 올라온 뒤 선 draw-on 애니메이션 실행.
  svg.querySelectorAll(".trend-line").forEach((poly, order) => animateDraw(poly, order));
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

  animateMetric("avg-rate", rate, { decimals: 1, suffix: "음절/초" });
  animateMetric("avg-pitch", pitch, { decimals: 0, suffix: "Hz" });
  animateMetric("sum-pause", pause, { decimals: 0, suffix: "회" });
  animateMetric("avg-smile", smile == null ? null : smile * 100, { decimals: 0, suffix: "%" });
  animateMetric("avg-gaze", gaze == null ? null : gaze * 100, { decimals: 0, suffix: "%" });
  animateMetric("sum-blink", blink, { decimals: 0, suffix: "회" });

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
  const dialogTurnCountEl = document.getElementById("dialog-turn-count");
  if (dialogTurnCountEl && report.turnCount != null) {
    dialogTurnCountEl.textContent = `${report.turnCount}개 답변`;
  }

  if (Array.isArray(report.turns)) {
    reportPagerState.turns = report.turns;
    reportPagerState.groups = normalizeTopicGroups(report);
    reportPagerState.groupIndex = Math.min(reportPagerState.groupIndex, Math.max(0, reportPagerState.groups.length - 1));

    // 종합(평균 비언어 지표) 카드 — 값이 차오르는 애니메이션
    renderSummary(report.turns);

    // 선택된 주제 그룹의 그래프와 다이얼로그를 함께 그립니다.
    renderTopicGroup();
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
// 진입 시 '평균 비언어 지표' 카드 위치로 자동 이동.
function scrollToSummary() {
  const target = document.getElementById("summary-title");
  if (target) {
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

async function init() {
  wireTopicPager("trend");
  wireTopicPager("dialog");
  const interviewId = interviewIdFromPath();
  if (!interviewId) {
    return; // 리포트 라우트가 아니면 아무것도 하지 않음
  }
  scrollToSummary();
  try {
    const report = await loadReportWithRetry(interviewId);
    renderReport(report); // 성공(또는 마지막 시도) → 받은 데이터로 교체
  } catch (error) {
    // 실패(API 미구현 / 네트워크 / 권한 없음) → 예시 데이터로 차트·애니메이션 표시
    console.info(`리포트 데이터를 불러오지 못해 예시 데이터로 표시합니다: ${error.message}`);
    renderReport(PLACEHOLDER_REPORT);
  }
}

init();
