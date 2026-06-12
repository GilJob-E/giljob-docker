import { Room, RoomEvent, setLogLevel } from "./vendor/livekit-client/dist/livekit-client.esm.mjs";

setLogLevel("silent");

const form = document.querySelector("#join-form");
const createButton = document.querySelector("#create-session");
const joinButton = document.querySelector("#join-room");
const leaveButton = document.querySelector("#leave-room");
const apiEndpointInput = document.querySelector("#api-endpoint");
const roleInput = document.querySelector("#role");
const publishMediaInput = document.querySelector("#publish-media");
const statusEl = document.querySelector("#status");
const logEl = document.querySelector("#event-log");
const summaryEl = document.querySelector("#session-summary");
const roomShell = document.querySelector("#room-shell");
const roomAppMain = document.querySelector(".room-app-main");
const roomStateEl = document.querySelector("#room-state");
const previewButton = document.querySelector("#start-preview");
const toggleMicButton = document.querySelector("#toggle-mic");
const toggleCameraButton = document.querySelector("#toggle-camera");
const localPreviewVideo = document.querySelector("#local-preview-video");
const candidateRoomVideo = document.querySelector("#candidate-room-video");
const previewPlaceholder = document.querySelector("#preview-placeholder");
const candidatePlaceholder = document.querySelector("#candidate-placeholder");
const candidateMediaState = document.querySelector("#candidate-media-state");
const candidateCaptions = document.querySelector("#candidate-captions");
const permissionNote = document.querySelector("#permission-note");
const interviewRouteLabel = document.querySelector("#interview-route-label");
const contextDrawer = document.querySelector("#room-context-drawer");
const toggleContextDrawerButton = document.querySelector("#toggle-context-drawer");
const closeContextDrawerButton = document.querySelector("#close-context-drawer");
const currentQuestionTitle = document.querySelector("#current-question-title");
const currentQuestionBody = document.querySelector("#current-question-body");
const interviewerQuestionText = document.querySelector("#interviewer-question-text");
const interviewerMediaState = document.querySelector("#interviewer-media-state");
const interviewerAudio = document.querySelector("#interviewer-audio");
const avatarSurface = document.querySelector("#avatar-surface");
const avatarRenderTarget = document.querySelector("#avatar-render-target");
const avatarStatusText = document.querySelector("#avatar-status-text");
const avatarPanelTitle = document.querySelector("#avatar-panel-title");
const avatarPanelBody = document.querySelector("#avatar-panel-body");
const transcriptBody = document.querySelector("#transcript-body");
const liveSignalsBody = document.querySelector("#live-signals-body");
const toggleSignalsBoxButton = document.querySelector("#toggle-signals-box");
const sigGaze = document.querySelector("#sig-gaze");
const sigRate = document.querySelector("#sig-rate");
const sigPause = document.querySelector("#sig-pause");
const sigExpression = document.querySelector("#sig-expression");
const sigPosture = document.querySelector("#sig-posture");
const sigCritique = document.querySelector("#sig-critique");
const qaDialogue = document.querySelector("#qa-dialogue");

let activeSession = null;
let activeRoom = null;
let localPreviewStream = null;
let micEnabled = false;
let cameraEnabled = false;
let answerTurnAvailable = false;
let nextQuestionRequested = false;
let currentTurnIndex = 1;
let lastAnswerTranscript = "";
let currentQuestionText = "";
let captionPollTimer = null;
let captionPollInFlight = false;
let activeAnalysisSessionId = "";
let activeAvatarSession = null;
let avatarRtcRuntime = { sdkInitialized: false, player: null, view: null, provider: null, avatarId: "" };
let avatarRtcInitializing = null;
let answerTurnStartRecordCount = 0;
const activeInterviewId = interviewIdFromPath(window.location.pathname);
const shouldAutoJoinRoom = isProductionRoomPath(window.location.pathname);

function redactSensitiveText(value) {
  return String(value)
    .replace(/access_token=[^'"\s&]+/g, "access_token=<redacted>")
    .replace(/join_request=[^'"\s&]+/g, "join_request=<redacted>")
    .replace(/eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+/g, "<jwt-redacted>")
    .replace(/gj_(session|report)_[A-Za-z0-9._-]+/g, "gj_$1_<redacted>");
}

function interviewIdFromPath(pathname) {
  const match = pathname.match(/^\/interviews\/([A-Za-z0-9][A-Za-z0-9._-]{0,95})\/room\/?$/);
  return match?.[1] ?? "local-demo";
}

function isProductionRoomPath(pathname) {
  return /^\/interviews\/[A-Za-z0-9][A-Za-z0-9._-]{0,95}\/room\/?$/.test(pathname) || pathname === "/interview-room.html";
}

function productionRouteFor(screen) {
  return `/interviews/${encodeURIComponent(activeInterviewId)}/${screen}`;
}

function hydrateProductionRoutes() {
  document.querySelectorAll("[data-interview-route]").forEach((link) => {
    const screen = link.dataset.interviewRoute;
    if (!screen) {
      return;
    }
    link.setAttribute("href", productionRouteFor(screen));
  });
  if (interviewRouteLabel) {
    interviewRouteLabel.textContent = activeInterviewId;
  }
}

function setContextDrawerOpen(isOpen) {
  if (!contextDrawer) {
    return;
  }
  contextDrawer.hidden = !isOpen;
  contextDrawer.setAttribute("aria-hidden", String(!isOpen));
  roomAppMain?.classList.toggle("is-context-open", isOpen);
  if (toggleContextDrawerButton) {
    toggleContextDrawerButton.setAttribute("aria-expanded", String(isOpen));
  }
}

function toggleContextDrawer() {
  setContextDrawerOpen(Boolean(contextDrawer?.hidden));
}

function appendLog(message) {
  if (!logEl) {
    return;
  }
  const timestamp = new Date().toISOString();
  logEl.textContent = `${timestamp} ${redactSensitiveText(message)}\n${logEl.textContent}`;
}

function setStatus(message, state = "idle") {
  if (!statusEl) {
    return;
  }
  statusEl.textContent = redactSensitiveText(message);
  statusEl.dataset.state = state;
}

function setRoomMode(mode) {
  if (roomShell) {
    roomShell.dataset.mode = mode;
  }
  const labels = {
    prejoin: "Disconnected",
    connecting: "Connecting",
    connected: "Connected",
  };
  if (roomStateEl) {
    roomStateEl.textContent = labels[mode] ?? mode;
  }
}

function valueOrDash(value) {
  return value ? String(value) : "-";
}

function avatarStatusLabel(payload) {
  const provider = payload?.provider || "disabled";
  if (payload?.ready) {
    return provider === "spatialreal" ? "SpatialReal 준비됨" : "Avatar 준비됨";
  }
  if (payload?.status === "disabled") {
    return "Avatar 비활성";
  }
  if (payload?.error) {
    return "Avatar 연결 실패";
  }
  return "Avatar 대기";
}

function avatarLiveKitConfig(payload) {
  const livekit = payload?.client?.livekit || {};
  const url = livekit.publicUrl || livekit.url;
  const token = livekit.avatarClientToken;
  const roomName = livekit.roomName || activeSession?.livekit?.roomName || activeSession?.roomName;
  if (!url || !token || !roomName || livekit.tokenStatus !== "issued") {
    return null;
  }
  return { url, token, roomName };
}

function setAvatarPanelMessage(message) {
  if (avatarPanelBody) {
    avatarPanelBody.textContent = message;
  }
}

function setAvatarRtcState(state, message) {
  if (avatarSurface) {
    avatarSurface.dataset.state = state;
  }
  if (avatarStatusText) {
    avatarStatusText.textContent = message;
  }
  if (avatarPanelTitle) {
    avatarPanelTitle.textContent = message;
  }
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

function renderAvatarRtcEgressStatus(avatarRtc) {
  if (!avatarRtc) {
    return;
  }
  const status = String(avatarRtc.status || "unknown");
  const reason = String(avatarRtc.reason || "");
  if (status === "sent") {
    setAvatarPanelMessage(`SpatialReal egress가 LiveKit room(${avatarRtc.roomName || "room"})으로 avatar stream을 보냈습니다. token은 숨겨집니다.`);
    appendLog(`avatar rtc egress sent; publisher ${avatarRtc.publisherId || "unknown"}; tokens hidden`);
    return;
  }
  if (status === "skipped") {
    setAvatarPanelMessage(`Avatar RTC egress 대기: ${reason || "not ready"}. TTS 오디오는 계속 재생됩니다.`);
    appendLog(`avatar rtc egress skipped: ${reason || "unknown"}; tokens hidden`);
    return;
  }
  if (status === "failed") {
    setAvatarPanelMessage(`Avatar RTC egress 실패: ${reason || "provider_request_failed"}. TTS 오디오는 계속 재생됩니다.`);
    appendLog(`avatar rtc egress failed: ${reason || "unknown"}; tokens hidden`);
  }
}

async function disconnectAvatarRtc() {
  const { player, view } = avatarRtcRuntime;
  avatarRtcRuntime = { sdkInitialized: avatarRtcRuntime.sdkInitialized, player: null, view: null, provider: null, avatarId: "" };
  if (player) {
    await player.disconnect().catch((error) => appendLog(`avatar rtc disconnect skipped: ${errorMessage(error)}`));
  }
  if (view) {
    view.dispose();
  }
  avatarRenderTarget?.classList.remove("is-rtc-active");
}

async function initializeAvatarRtc(payload) {
  if (!payload?.ready || payload?.provider !== "spatialreal") {
    return;
  }
  if (avatarRtcInitializing) {
    return avatarRtcInitializing;
  }
  avatarRtcInitializing = (async () => {
    const client = payload.client || {};
    const appId = client.appId;
    const avatarId = client.avatarId;
    const sessionToken = client.sessionToken;
    const livekitConfig = avatarLiveKitConfig(payload);
    if (!appId || !avatarId || !sessionToken || !livekitConfig) {
      setAvatarPanelMessage("SpatialReal session은 준비됐지만 AvatarKit RTC용 LiveKit viewer token이 아직 없습니다. token은 화면과 로그에 출력하지 않습니다.");
      appendLog("avatar rtc waiting for app/avatar/session/livekit viewer config; tokens hidden");
      return;
    }

    try {
      setAvatarRtcState("ready", "Avatar RTC 준비 중");
      const [{ AvatarSDK, AvatarManager, AvatarView, DrivingServiceMode, Environment, LogLevel }, { AvatarPlayer, LiveKitProvider }] = await Promise.all([
        import("./vendor/@spatialwalk/avatarkit/dist/index.js"),
        import("./vendor/@spatialwalk/avatarkit-rtc/dist/index.js"),
      ]);

      if (!AvatarSDK.isInitialized) {
        await AvatarSDK.initialize(appId, {
          environment: Environment.intl,
          drivingServiceMode: DrivingServiceMode.host,
          logLevel: LogLevel.warning,
          audioFormat: {
            channelCount: client.audioFormat?.channelCount || 1,
            sampleRate: client.audioFormat?.sampleRate || 16000,
          },
        });
        avatarRtcRuntime.sdkInitialized = true;
      }
      AvatarSDK.setSessionToken(sessionToken);

      if (!avatarRenderTarget) {
        throw new Error("avatar render target is missing");
      }
      await disconnectAvatarRtc();
      setAvatarPanelMessage("AvatarKit RTC가 avatar asset을 불러오는 중입니다. token은 숨겨집니다.");
      const avatar = await AvatarManager.shared.load(avatarId, (progress) => {
        if (progress?.type === "downloading" && typeof progress.progress === "number") {
          setAvatarPanelMessage(`Avatar asset 다운로드 중 ${Math.round(progress.progress * 100)}%. token은 숨겨집니다.`);
        }
      }, true);
      const view = new AvatarView(avatar, avatarRenderTarget);
      const provider = new LiveKitProvider();
      const player = new AvatarPlayer(provider, view, { logLevel: "warning" });
      player.on("connected", () => {
        setAvatarRtcState("ready", "Avatar RTC 연결됨");
        setAvatarPanelMessage("SpatialReal RTC renderer가 LiveKit room에 연결됐습니다. 서버 egress/publisher가 avatar stream을 보내면 이 타일에 렌더링됩니다.");
        appendLog("avatar rtc connected through LiveKit; tokens hidden");
      });
      player.on("disconnected", () => appendLog("avatar rtc disconnected"));
      player.on("stalled", () => appendLog("avatar rtc stalled; waiting for SpatialReal publisher frames"));
      player.on("error", (error) => {
        const message = errorMessage(error);
        setAvatarRtcState("error", "Avatar RTC 오류");
        setAvatarPanelMessage(`AvatarKit RTC 오류: ${message}`);
        appendLog(`avatar rtc error: ${message}`);
      });
      await player.connect(livekitConfig);
      avatarRenderTarget.classList.add("is-rtc-active");
      avatarRtcRuntime = { sdkInitialized: true, player, view, provider, avatarId };
    } catch (error) {
      const message = errorMessage(error);
      setAvatarRtcState("error", "Avatar RTC 연결 실패");
      setAvatarPanelMessage(`AvatarKit RTC 연결 실패: ${message}`);
      appendLog(`avatar rtc failed: ${message}`);
    } finally {
      avatarRtcInitializing = null;
    }
  })();
  return avatarRtcInitializing;
}

function renderAvatarState(payload) {
  activeAvatarSession = payload || null;
  const state = payload?.ready ? "ready" : payload?.error ? "error" : payload?.status === "disabled" ? "disabled" : "pending";
  const label = avatarStatusLabel(payload);
  if (avatarSurface) {
    avatarSurface.dataset.state = state;
  }
  if (avatarStatusText) {
    avatarStatusText.textContent = label;
  }
  if (avatarPanelTitle) {
    avatarPanelTitle.textContent = label;
  }
  if (avatarPanelBody) {
    if (payload?.ready) {
      const audio = payload?.client?.audioFormat || {};
      const livekit = payload?.client?.livekit || {};
      const rtcStatus = livekit.tokenStatus === "issued" ? "AvatarKit RTC viewer token 준비됨" : "AvatarKit RTC viewer token 대기";
      avatarPanelBody.textContent = `SpatialReal session이 발급되었습니다. session token은 화면에 표시하지 않습니다. Audio ${audio.channelCount || 1}ch/${audio.sampleRate || 16000}Hz. ${rtcStatus}.`;
    } else if (payload?.reason) {
      avatarPanelBody.textContent = `상태: ${payload.reason}. 키가 구성되면 서버가 session token을 중개합니다.`;
    } else if (payload?.error) {
      avatarPanelBody.textContent = `Avatar provider 오류: ${payload.message || payload.error}`;
    } else {
      avatarPanelBody.textContent = "Provider 상태를 확인하는 중입니다.";
    }
  }
}

async function requestAvatarSession(reason = "room-join") {
  renderAvatarState({ status: "pending", provider: "spatialreal", ready: false });
  try {
    const response = await fetch(`/api/interviews/${encodeURIComponent(activeInterviewId)}/avatar/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.message || payload.error || `avatar session failed: HTTP ${response.status}`);
    }
    renderAvatarState(payload);
    appendLog(`avatar session state: ${payload.status || "unknown"}; provider ${payload.provider || "unknown"}; session token hidden`);
    initializeAvatarRtc(payload);
    return payload;
  } catch (error) {
    const message = errorMessage(error);
    const payload = { error: "avatar_session_failed", message, ready: false };
    renderAvatarState(payload);
    appendLog(`avatar session failed: ${message}`);
    return payload;
  }
}

function renderInterviewQuestion(question) {
  const text = question?.question || "질문을 불러오지 못했습니다.";
  const title = question?.questionId ? `질문 ${question.turnIndex || currentTurnIndex}` : "질문 준비 실패";
  if (currentQuestionTitle) {
    currentQuestionTitle.textContent = title;
  }
  if (currentQuestionBody) {
    currentQuestionBody.textContent = text;
  }
  currentQuestionText = text;
  if (interviewerQuestionText) {
    interviewerQuestionText.textContent = text;
  }
  if (interviewerMediaState) {
    interviewerMediaState.textContent = "질문 완료";
  }
  if (avatarSurface) {
    avatarSurface.dataset.state = activeAvatarSession?.ready ? "speaking" : avatarSurface.dataset.state || "disabled";
  }
}

function renderTranscriptStatus(message) {
  if (transcriptBody) {
    transcriptBody.textContent = message;
  }
}

// Live STT captions over the candidate tile. The analysis-engine writes ~3s
// finalized transcript windows to the signal snapshot; while the candidate is
// answering we poll and show the most recent windows as a rolling subtitle.
// Text is redaction-guarded and rendered via textContent only.
function setCaptions(text) {
  if (!candidateCaptions) {
    return;
  }
  const value = String(text || "").trim();
  candidateCaptions.textContent = redactSensitiveText(value);
  candidateCaptions.hidden = value.length === 0;
}

async function pollCaptions(sessionId) {
  if (captionPollInFlight) {
    return;
  }
  captionPollInFlight = true;
  try {
    const payload = await fetchAnalysisSignals(sessionId);
    const records = Array.isArray(payload?.records)
      ? payload.records.slice(answerTurnStartRecordCount)
      : [];
    const windows = records
      .filter((record) => record?.type === "window" && String(record?.transcript || "").trim())
      .map((record) => String(record.transcript).trim());
    if (windows.length) {
      // rolling subtitle: last ~2 finalized windows (~6s of speech)
      setCaptions(windows.slice(-2).join(" "));
    }
  } catch {
    // transient poll failure: keep the last caption, do not spam the log
  } finally {
    captionPollInFlight = false;
  }
}

function startCaptionPolling(sessionId) {
  stopCaptionPolling();
  setCaptions("듣고 있습니다…");
  pollCaptions(sessionId);
  captionPollTimer = window.setInterval(() => pollCaptions(sessionId), 1200);
}

function stopCaptionPolling() {
  if (captionPollTimer) {
    window.clearInterval(captionPollTimer);
    captionPollTimer = null;
  }
  setCaptions("");
}

// Accumulating Q&A dialogue: one entry per completed turn, with the question,
// the answer transcript, and an expandable per-turn evaluation. DOM is built
// with createElement/textContent only (no raw markup injection) and every
// rendered string is redaction-guarded, matching the room's token-safety contract.
function buildQaRow(label, text) {
  const row = document.createElement("div");
  row.className = label === "Q" ? "qa-row qa-q" : "qa-row qa-a";
  const tag = document.createElement("span");
  tag.className = "qa-tag";
  tag.textContent = label;
  const body = document.createElement("p");
  body.className = "qa-text";
  body.textContent = redactSensitiveText(text);
  row.append(tag, body);
  return row;
}

function appendEvalGroup(details, label, lines) {
  const visible = lines.filter((line) => typeof line === "string" && line.trim());
  if (!visible.length) {
    return;
  }
  const group = document.createElement("div");
  group.className = "qa-eval-group";
  const heading = document.createElement("p");
  heading.className = "qa-eval-label";
  heading.textContent = label;
  group.appendChild(heading);
  for (const line of visible) {
    const para = document.createElement("p");
    para.className = "qa-eval-line";
    para.textContent = redactSensitiveText(line);
    group.appendChild(para);
  }
  details.appendChild(group);
}

function buildEvalDetails(evaluation) {
  const details = document.createElement("details");
  details.className = "qa-eval";
  const summary = document.createElement("summary");
  summary.textContent = "평가 펼치기";
  details.appendChild(summary);

  const verbal = evaluation.verbal || {};
  const vocal = evaluation.vocal || {};
  const visual = evaluation.visual || {};
  appendEvalGroup(details, "언어", [verbal.logic, verbal.structure, verbal.specificity]);
  appendEvalGroup(details, "음성", [vocal.pace, vocal.intonation, vocal.pauses, vocal.volume]);
  appendEvalGroup(details, "시각", [visual.eye_contact, visual.expression, visual.posture]);

  const critique = Array.isArray(evaluation.critique) ? evaluation.critique.filter(Boolean) : [];
  if (critique.length) {
    const group = document.createElement("div");
    group.className = "qa-eval-group";
    const heading = document.createElement("p");
    heading.className = "qa-eval-label";
    heading.textContent = "핵심 지적";
    const list = document.createElement("ul");
    list.className = "qa-critique-list";
    for (const item of critique) {
      const li = document.createElement("li");
      li.textContent = redactSensitiveText(item);
      list.appendChild(li);
    }
    group.append(heading, list);
    details.appendChild(group);
  }
  return details;
}

function appendDialogueTurn(question, answer, evaluation) {
  if (!qaDialogue) {
    return;
  }
  const empty = qaDialogue.querySelector(".qa-empty");
  if (empty) {
    empty.remove();
  }
  const turnNumber = qaDialogue.querySelectorAll(".qa-turn").length + 1;
  const item = document.createElement("li");
  item.className = "qa-turn";

  const head = document.createElement("p");
  head.className = "qa-turn-head";
  head.textContent = `턴 ${turnNumber}`;
  item.appendChild(head);

  item.appendChild(buildQaRow("Q", question || "질문 기록 없음"));
  item.appendChild(buildQaRow("A", answer || "전사 결과가 비어 있습니다."));
  if (evaluation && typeof evaluation === "object") {
    item.appendChild(buildEvalDetails(evaluation));
  }
  qaDialogue.appendChild(item);
}

// Live state box: project the analysis-engine signal payload (kor-signals shape)
// into the candidate-state box. Only summarized, token/media-safe fields are
// shown; the raw eval text is redaction-guarded like every other rendered value.
function signalPercent(value) {
  return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value * 100)}%` : null;
}

function latestEvalRecord(payload) {
  const records = Array.isArray(payload?.records) ? payload.records : [];
  return [...records].reverse().find((record) => record?.type === "eval" && record?.eval) || null;
}

function renderLiveSignals(payload) {
  const record = latestEvalRecord(payload);
  if (!record) {
    return;
  }
  const evaluation = record.eval || {};
  const visual = evaluation.objective_visual || {};
  const vocal = evaluation.objective_vocal || {};
  const faceSeen = Number(visual.face_seen_ratio ?? 0) > 0;

  if (sigGaze) {
    const gaze = signalPercent(visual.gaze_off_mean);
    sigGaze.textContent = faceSeen && gaze ? `${gaze} 이탈` : "측정 불가";
  }
  if (sigRate) {
    const rate = vocal?.rate?.speech_rate_syl_per_s;
    sigRate.textContent = typeof rate === "number"
      ? `${rate.toFixed(1)} 음절/초 · ${rate < 4.5 ? "느림" : rate > 6.5 ? "빠름" : "적정"}`
      : "측정 불가";
  }
  if (sigPause) {
    const longPause = vocal?.pauses?.pause_count_ge_0p25;
    const shortJuncture = vocal?.pauses?.short_juncture_count_0p1_0p25;
    sigPause.textContent = typeof longPause === "number" || typeof shortJuncture === "number"
      ? `긴 휴지 ${longPause ?? 0}회 · 짧은 끊김 ${shortJuncture ?? 0}회`
      : "측정 불가";
  }
  if (sigExpression) {
    const smile = signalPercent(visual.smile_ratio);
    sigExpression.textContent = faceSeen && smile ? `미소 ${smile}` : "측정 불가";
  }
  if (sigPosture) {
    const sway = visual.head_sway;
    sigPosture.textContent = faceSeen && typeof sway === "number"
      ? (sway < 0.02 ? "안정" : sway < 0.05 ? "보통" : "흔들림 큼")
      : "측정 불가";
  }
  if (sigCritique) {
    const critique = Array.isArray(evaluation.critique) && evaluation.critique.length
      ? evaluation.critique[0]
      : (Array.isArray(evaluation.key_observations) && evaluation.key_observations.length ? evaluation.key_observations[0] : "");
    sigCritique.textContent = critique
      ? redactSensitiveText(critique)
      : "분석이 도출되면 평가 요약이 표시됩니다.";
  }
}

function analysisSessionId() {
  return activeSession?.sessionId || activeInterviewId;
}

async function postAnalysis(path, body = {}) {
  const response = await fetch(`/analysis${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.message || payload.error || `analysis request failed: HTTP ${response.status}`);
  }
  return payload;
}

async function fetchAnalysisSignals(sessionId) {
  const response = await fetch(`/analysis/signals?sessionId=${encodeURIComponent(sessionId)}`);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.message || payload.error || `analysis signals failed: HTTP ${response.status}`);
  }
  return payload;
}

function renderAnalysisTranscript(payload, sinceRecordCount = 0) {
  const records = Array.isArray(payload?.records) ? payload.records.slice(sinceRecordCount) : [];
  const latestTurnEnd = [...records].reverse().find((record) => record?.type === "turn_end");
  const windowTranscripts = records
    .filter((record) => record?.type === "window" && String(record?.transcript || "").trim())
    .map((record) => String(record.transcript).trim());
  const transcript = (latestTurnEnd?.transcript_full || windowTranscripts.join(" ") || "").trim();
  if (transcript) {
    renderTranscriptStatus(transcript);
    return transcript;
  }
  const count = Number(payload?.recordCount || 0) - sinceRecordCount;
  renderTranscriptStatus(count > 0 ? "전사 window는 수신됐지만 최종 turn transcript가 비어 있습니다." : "아직 수신된 전사 signal이 없습니다.");
  return "";
}

async function restartAnalysisSubscriber(sessionId) {
  try {
    await postAnalysis("/subscriber/stop", {});
  } catch (error) {
    appendLog(`analysis subscriber stop skipped: ${errorMessage(error)}`);
  }
  const payload = await postAnalysis("/subscriber/start", { sessionId, criticMode: "window" });
  activeAnalysisSessionId = sessionId;
  appendLog(`analysis subscriber ready for session ${sessionId}; state ${payload.status || payload.state || "starting"}`);
  renderTranscriptStatus("GilJobE analysis-engine이 답변 오디오를 기다리고 있습니다.");
  return payload;
}

async function fetchSignalsAfterTurnFlush(sessionId, sinceRecordCount) {
  let payload = null;
  for (let attempt = 0; attempt < 8; attempt += 1) {
    payload = await fetchAnalysisSignals(sessionId);
    const records = Array.isArray(payload.records) ? payload.records.slice(sinceRecordCount) : [];
    const hasTurnEnd = records.some((record) => record?.type === "turn_end");
    if (hasTurnEnd || (records.length > 0 && attempt >= 2)) {
      return payload;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return payload || { records: [], recordCount: sinceRecordCount };
}

async function markAnalysisTurnStart(sessionId) {
  try {
    const payload = await fetchAnalysisSignals(sessionId);
    answerTurnStartRecordCount = Number(payload.recordCount || 0);
  } catch (error) {
    answerTurnStartRecordCount = 0;
    appendLog(`analysis turn baseline unavailable: ${errorMessage(error)}`);
  }
}

async function flushAnalysisTurn(sessionId) {
  await new Promise((resolve) => setTimeout(resolve, 1000));
  try {
    await postAnalysis("/subscriber/stop", {});
    const payload = await fetchSignalsAfterTurnFlush(sessionId, answerTurnStartRecordCount);
    const transcript = renderAnalysisTranscript(payload, answerTurnStartRecordCount);
    renderLiveSignals(payload);
    appendDialogueTurn(currentQuestionText, transcript, latestEvalRecord(payload)?.eval || null);
    appendLog(`analysis turn flushed for session ${sessionId}; records ${payload.recordCount || 0}`);
    try {
      await postAnalysis("/subscriber/start", { sessionId, criticMode: "window" });
      activeAnalysisSessionId = sessionId;
    } catch (restartError) {
      appendLog(`analysis subscriber restart failed: ${errorMessage(restartError)}`);
    }
    return transcript;
  } catch (error) {
    const message = errorMessage(error);
    renderTranscriptStatus(`전사 flush 실패: ${message}`);
    appendLog(`analysis turn flush failed: ${message}`);
    return "";
  }
}

function renderQuestionLoading() {
  if (currentQuestionTitle) {
    currentQuestionTitle.textContent = "질문 생성 중";
  }
  if (currentQuestionBody) {
    currentQuestionBody.textContent = "Gemini 기반 InterviewController가 다음 질문을 생성하고 있습니다.";
  }
  if (interviewerQuestionText) {
    interviewerQuestionText.textContent = "면접관 질문을 준비하고 있습니다.";
  }
  if (interviewerMediaState) {
    interviewerMediaState.textContent = "질문 생성 중";
  }
  if (avatarSurface && activeAvatarSession?.ready) {
    avatarSurface.dataset.state = "ready";
  }
}

function audioDataUrl(audio) {
  if (!audio?.base64 || !audio?.contentType) {
    return "";
  }
  return `data:${audio.contentType};base64,${audio.base64}`;
}

function markInterviewerQuestionEnded(payload) {
  if (avatarSurface && activeAvatarSession?.ready) {
    avatarSurface.dataset.state = "ready";
  }
  document.dispatchEvent(new CustomEvent("giljob:interviewer-question-ended", { detail: payload }));
}

async function playInterviewerQuestion(payload) {
  const turnIndex = Number(payload?.turnIndex || currentTurnIndex);
  const questionText = String(payload?.question || "").trim();
  if (!questionText) {
    appendLog("tts skipped: empty interviewer question");
    return;
  }
  if (interviewerMediaState) {
    interviewerMediaState.textContent = "TTS 준비 중";
  }
  try {
    const response = await fetch(`/api/interviews/${encodeURIComponent(activeInterviewId)}/turns/${turnIndex}/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: questionText }),
    });
    const ttsPayload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(ttsPayload.message || ttsPayload.error || `tts request failed: HTTP ${response.status}`);
    }
    renderAvatarRtcEgressStatus(ttsPayload.avatarRtc);
    const dataUrl = audioDataUrl(ttsPayload.audio);
    if (!dataUrl || !interviewerAudio) {
      appendLog(`tts audio unavailable; provider ${ttsPayload.audio?.provider || "unknown"}`);
      return;
    }
    interviewerAudio.src = dataUrl;
    if (interviewerMediaState) {
      interviewerMediaState.textContent = "질문 재생 중";
    }
    if (avatarSurface && activeAvatarSession?.ready) {
      avatarSurface.dataset.state = "speaking";
    }
    appendLog(`interviewer tts ready; provider ${ttsPayload.audio?.provider || "unknown"}; audio bytes ${ttsPayload.audio?.byteLength || 0}; audio hidden`);
    await interviewerAudio.play();
    await new Promise((resolve) => {
      if (interviewerAudio.ended || interviewerAudio.paused) {
        resolve();
        return;
      }
      const done = () => {
        interviewerAudio.removeEventListener("ended", done);
        interviewerAudio.removeEventListener("error", done);
        resolve();
      };
      interviewerAudio.addEventListener("ended", done, { once: true });
      interviewerAudio.addEventListener("error", done, { once: true });
    });
  } catch (error) {
    appendLog(`interviewer tts playback skipped: ${errorMessage(error)}`);
  } finally {
    if (interviewerMediaState) {
      interviewerMediaState.textContent = "질문 완료";
    }
  }
}

async function requestNextQuestion(reason = "manual") {
  if (nextQuestionRequested) {
    return;
  }
  nextQuestionRequested = true;
  document.dispatchEvent(new CustomEvent("giljob:interviewer-question-started"));
  renderQuestionLoading();
  appendLog(`requesting next interviewer question: ${reason}`);
  try {
    const response = await fetch(`/api/interviews/${encodeURIComponent(activeInterviewId)}/turns/${currentTurnIndex}/question`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        persona: "차분하고 명확한 한국어 면접관",
        candidateProfile: "not provided in this slice",
        job: "not provided in this slice",
        lastAnswer: lastAnswerTranscript || "아직 이전 답변 전사가 없습니다.",
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.message || payload.error || `question request failed: HTTP ${response.status}`);
    }
    renderInterviewQuestion(payload);
    appendLog(`interviewer question ready: ${payload.questionId || "question"}; provider ${payload.provider || "unknown"}`);
    await playInterviewerQuestion(payload);
    markInterviewerQuestionEnded(payload);
  } catch (error) {
    const message = errorMessage(error);
    nextQuestionRequested = false;
    renderInterviewQuestion(null);
    if (interviewerMediaState) {
      interviewerMediaState.textContent = "질문 실패";
    }
    setStatus(`question request failed: ${message}`, "error");
    appendLog(`question request failed: ${message}`);
  }
}

function renderSessionSummary(session) {
  if (!summaryEl) {
    return;
  }
  const livekit = session?.livekit ?? {};
  const rows = [
    ["interviewId", activeInterviewId],
    ["sessionId", session?.sessionId],
    ["roomName", session?.roomName ?? livekit.roomName],
    ["LiveKit URL", livekit.publicUrl ?? livekit.url],
    ["tokenStatus", livekit.tokenStatus],
    ["participant", livekit.participantIdentity],
  ];
  summaryEl.replaceChildren(
    ...rows.map(([label, value]) => {
      const row = document.createElement("div");
      const term = document.createElement("dt");
      const detail = document.createElement("dd");
      term.textContent = label;
      detail.textContent = valueOrDash(value);
      row.append(term, detail);
      return row;
    }),
  );
}

function setButtonPressed(button, isPressed, onLabel, offLabel) {
  if (!button) {
    return;
  }
  button.setAttribute("aria-pressed", String(isPressed));
  button.textContent = isPressed ? onLabel : offLabel;
  button.dataset.enabled = String(isPressed);
}

function syncAnswerTurnButton() {
  if (!toggleMicButton) {
    return;
  }
  const shouldDisable = !answerTurnAvailable && !micEnabled;
  toggleMicButton.disabled = shouldDisable;
  toggleMicButton.setAttribute("aria-disabled", String(shouldDisable));
  toggleMicButton.title = shouldDisable ? "면접관 질문이 끝나면 답변 시작 버튼이 활성화됩니다." : "";
}

function setAnswerTurnAvailability(isAvailable, reason = "") {
  answerTurnAvailable = Boolean(isAvailable);
  syncAnswerTurnButton();
  if (reason) {
    appendLog(reason);
  }
}

function syncMediaUi() {
  if (publishMediaInput) {
    publishMediaInput.checked = micEnabled || cameraEnabled;
  }
  setButtonPressed(toggleMicButton, micEnabled, "답변 종료", "답변 시작");
  syncAnswerTurnButton();
  setButtonPressed(toggleCameraButton, cameraEnabled, "Camera on", "Camera off");
  const hasCameraPreview = Boolean(cameraEnabled && localPreviewStream);
  if (localPreviewVideo) {
    localPreviewVideo.hidden = !hasCameraPreview;
  }
  if (candidateRoomVideo) {
    candidateRoomVideo.hidden = !hasCameraPreview;
  }
  if (previewPlaceholder) {
    previewPlaceholder.hidden = hasCameraPreview;
  }
  if (candidatePlaceholder) {
    candidatePlaceholder.hidden = hasCameraPreview;
  }
  if (candidateMediaState) {
    candidateMediaState.textContent = `답변 ${micEnabled ? "중" : "대기"} · Camera ${cameraEnabled ? "on" : "off"}`;
  }
  if (permissionNote) {
    permissionNote.textContent = hasCameraPreview
      ? "카메라 프리뷰는 브라우저 로컬에서만 표시됩니다."
      : "입장 전 카메라/마이크를 켜서 권한과 프리뷰를 확인할 수 있습니다.";
  }
}

function stopPreviewStream() {
  if (!localPreviewStream) {
    return;
  }
  localPreviewStream.getTracks().forEach((track) => track.stop());
  localPreviewStream = null;
  if (localPreviewVideo) {
    localPreviewVideo.srcObject = null;
  }
  if (candidateRoomVideo) {
    candidateRoomVideo.srcObject = null;
  }
}

async function restartPreviewStream() {
  stopPreviewStream();
  if (!micEnabled && !cameraEnabled) {
    syncMediaUi();
    appendLog("local preview stopped; mic/camera off");
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    micEnabled = false;
    cameraEnabled = false;
    syncMediaUi();
    throw new Error("browser media permissions are not available");
  }

  setStatus("requesting media permission...", "connecting");
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: micEnabled,
    video: cameraEnabled ? { width: { ideal: 1280 }, height: { ideal: 720 } } : false,
  });
  localPreviewStream = stream;
  if (cameraEnabled) {
    if (localPreviewVideo) {
      localPreviewVideo.srcObject = stream;
    }
    if (candidateRoomVideo) {
      candidateRoomVideo.srcObject = stream;
    }
  }
  syncMediaUi();
  setStatus("preview ready", activeRoom ? "connected" : "idle");
  appendLog(`candidate answer turn ${micEnabled ? "started" : "idle"}; camera ${cameraEnabled ? "on" : "off"}; tokens hidden`);
}

async function startPreview() {
  if (!micEnabled && !cameraEnabled) {
    cameraEnabled = true;
  }
  await restartPreviewStream();
}

async function applyMediaStateToRoom() {
  if (!activeRoom) {
    return;
  }
  await activeRoom.localParticipant.setMicrophoneEnabled(micEnabled);
  await activeRoom.localParticipant.setCameraEnabled(cameraEnabled);
  appendLog(`room media updated: answer ${micEnabled ? "recording" : "ended"}, camera ${cameraEnabled ? "on" : "off"}`);
}

async function startAnswerCapture() {
  await markAnalysisTurnStart(analysisSessionId());
  startCaptionPolling(analysisSessionId());
  renderTranscriptStatus("답변 중입니다. GilJobE analysis-engine이 LiveKit 오디오를 수집하고 있습니다.");
  appendLog("candidate answer turn started; GilJobE analysis-engine recording boundary active");
}

async function submitTurnAnswer(turnIndex, answer) {
  // Real-time per-turn persistence: store this turn's answer and let the API
  // ingest the turn's analysis signals as soon as the answer completes.
  if (!answer) {
    return;
  }
  try {
    await fetch(`/api/interviews/${encodeURIComponent(activeInterviewId)}/turns/${turnIndex}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer }),
    });
    appendLog(`turn ${turnIndex} answer submitted; real-time signal ingest requested`);
  } catch (error) {
    appendLog(`turn answer submit skipped: ${errorMessage(error)}`);
  }
}

async function finalizeInterview() {
  // Interview over: ask the API for a final signal-ingest sweep (captures the
  // last turn's eval windows). Best-effort; never blocks leaving the room.
  try {
    await fetch(`/api/interviews/${encodeURIComponent(activeInterviewId)}/finalize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ turnIndex: currentTurnIndex, answer: lastAnswerTranscript }),
    });
    appendLog("interview finalized; final signal ingest requested");
  } catch (error) {
    appendLog(`finalize skipped: ${errorMessage(error)}`);
  }
}

async function finishAnswerAndRequestNextQuestion() {
  micEnabled = false;
  stopCaptionPolling();
  await restartPreviewStream();
  await applyMediaStateToRoom();
  const sessionId = analysisSessionId();
  renderTranscriptStatus("답변 종료. GilJobE analysis-engine에서 최종 전사를 가져오는 중입니다.");
  const transcript = await flushAnalysisTurn(sessionId);
  lastAnswerTranscript = transcript || "전사 결과가 비어 있습니다.";
  submitTurnAnswer(currentTurnIndex, transcript);
  currentTurnIndex += 1;
  nextQuestionRequested = false;
  setAnswerTurnAvailability(false, "candidate answer ended; waiting for next interviewer question");
  requestNextQuestion("candidate-answer-ended-analysis-flushed");
}

async function toggleMic() {
  if (!micEnabled && !answerTurnAvailable) {
    appendLog("answer start blocked until interviewer question ends");
    return;
  }
  try {
    if (!micEnabled) {
      micEnabled = true;
      await restartPreviewStream();
      await applyMediaStateToRoom();
      await startAnswerCapture();
      return;
    }
    await finishAnswerAndRequestNextQuestion();
  } catch (error) {
    const message = errorMessage(error);
    micEnabled = false;
    stopCaptionPolling();
    stopPreviewStream();
    syncMediaUi();
    setStatus(`answer turn failed: ${message}`, "error");
    appendLog(`answer turn failed: ${message}`);
  }
}

async function toggleCamera() {
  cameraEnabled = !cameraEnabled;
  try {
    await restartPreviewStream();
    await applyMediaStateToRoom();
  } catch (error) {
    const message = errorMessage(error);
    micEnabled = false;
    cameraEnabled = false;
    stopPreviewStream();
    syncMediaUi();
    setStatus(`media permission failed: ${message}`, "error");
    appendLog(`media permission failed: ${message}`);
  }
}

function sessionLiveKitConfig(session) {
  const livekit = session?.livekit;
  const url = livekit?.publicUrl ?? livekit?.url;
  const token = livekit?.candidateToken;
  if (!url || !token) {
    const reason = livekit?.deferredReason ?? "missing LiveKit URL/token";
    throw new Error(`LiveKit join is not available: ${reason}`);
  }
  return { url, token };
}

async function createSession() {
  const endpoint = apiEndpointInput?.value.trim() || "/api/sessions";
  const role = roleInput?.value.trim() || "candidate";
  setStatus("creating session...", "connecting");
  appendLog(`POST ${endpoint}`);

  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role, sessionId: activeInterviewId, interviewId: activeInterviewId }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.message || payload.error || `session request failed: HTTP ${response.status}`);
  }

  activeSession = payload;
  renderSessionSummary(activeSession);
  setStatus(`session created: ${payload.roomName}`, "idle");
  appendLog(`session created for room ${payload.roomName}; tokens hidden`);
  await requestAvatarSession("session-created");
  return activeSession;
}

function bindRoomEvents(room) {
  room
    .on(RoomEvent.ConnectionStateChanged, (state) => {
      const normalized = String(state).toLowerCase();
      const uiState = normalized.includes("connected") ? "connected" : normalized.includes("connecting") ? "connecting" : "idle";
      setStatus(`LiveKit ${state}`, uiState);
      appendLog(`LiveKit state: ${state}`);
    })
    .on(RoomEvent.Connected, () => {
      setRoomMode("connected");
      setStatus("LiveKit connected", "connected");
      if (leaveButton) {
        leaveButton.disabled = false;
      }
      if (joinButton) {
        joinButton.disabled = true;
      }
      appendLog("LiveKit connected");
      requestNextQuestion("room-connected");
    })
    .on(RoomEvent.Disconnected, (reason) => {
      setRoomMode("prejoin");
      setStatus(`LiveKit disconnected${reason ? `: ${reason}` : ""}`, "idle");
      if (leaveButton) {
        leaveButton.disabled = true;
      }
      if (joinButton) {
        joinButton.disabled = false;
      }
      appendLog(`LiveKit disconnected${reason ? `: ${reason}` : ""}`);
    })
    .on(RoomEvent.Reconnecting, () => appendLog("LiveKit reconnecting"))
    .on(RoomEvent.Reconnected, () => appendLog("LiveKit reconnected"))
    .on(RoomEvent.ParticipantConnected, (participant) => appendLog(`participant connected: ${participant.identity}`))
    .on(RoomEvent.ParticipantDisconnected, (participant) => appendLog(`participant disconnected: ${participant.identity}`));
}

async function maybePublishLocalMedia(room) {
  if (!micEnabled && !cameraEnabled) {
    appendLog("media publish skipped (mic/camera off)");
    return;
  }
  appendLog(`publishing local media: answer ${micEnabled ? "recording" : "idle"}, camera ${cameraEnabled ? "on" : "off"}`);
  await room.localParticipant.setMicrophoneEnabled(micEnabled);
  await room.localParticipant.setCameraEnabled(cameraEnabled);
  appendLog("local microphone/camera publish state applied");
}

async function disableLocalMedia(room) {
  if (!room?.localParticipant) {
    return;
  }
  await Promise.allSettled([
    room.localParticipant.setMicrophoneEnabled(false),
    room.localParticipant.setCameraEnabled(false),
  ]);
}

async function failClosedAfterJoinMediaError(room, error) {
  appendLog(`media publish failed after join; disconnecting room fail-closed: ${errorMessage(error)}`);
  await disableLocalMedia(room);
  room.disconnect();
  if (activeRoom === room) {
    activeRoom = null;
  }
  if (leaveButton) {
    leaveButton.disabled = true;
  }
  if (joinButton) {
    joinButton.disabled = false;
  }
  setRoomMode("prejoin");
}

async function joinRoom() {
  const session = activeSession ?? (await createSession());
  const { url, token } = sessionLiveKitConfig(session);
  try {
    await restartAnalysisSubscriber(session.sessionId || activeInterviewId);
  } catch (error) {
    appendLog(`analysis subscriber unavailable before join: ${errorMessage(error)}`);
    renderTranscriptStatus("analysis-engine 연결을 확인하지 못했습니다. LiveKit 입장은 계속 진행합니다.");
  }
  if (activeRoom) {
    activeRoom.disconnect();
  }

  setRoomMode("connecting");
  setStatus("connecting to LiveKit...", "connecting");
  activeRoom = new Room();
  bindRoomEvents(activeRoom);
  appendLog(`connecting to ${url} as ${session.livekit.participantIdentity}; token hidden`);
  await activeRoom.connect(url, token);
  try {
    await maybePublishLocalMedia(activeRoom);
  } catch (error) {
    await failClosedAfterJoinMediaError(activeRoom, error);
    throw error;
  }
}

async function autoJoinRoomRoute() {
  if (!shouldAutoJoinRoom) {
    return;
  }
  try {
    await joinRoom();
  } catch (error) {
    const message = errorMessage(error);
    setRoomMode("prejoin");
    setStatus(message, "error");
    appendLog(`error: ${message}`);
    if (leaveButton) {
      leaveButton.disabled = true;
    }
  }
}

function leaveRoom() {
  if (!activeRoom) {
    return;
  }
  // Leave now doubles as "end interview + open report"; confirm before tearing down.
  if (!window.confirm("현재 면접을 종료하고 지금까지의 레포트를 확인합니다.")) {
    return;
  }
  appendLog("leaving LiveKit room");
  stopCaptionPolling();
  finalizeInterview();
  disconnectAvatarRtc();
  activeRoom.disconnect();
  activeRoom = null;
  if (leaveButton) {
    leaveButton.disabled = true;
  }
  if (joinButton) {
    joinButton.disabled = false;
  }
  window.location.assign(productionRouteFor("report"));
}

createButton?.addEventListener("click", async () => {
  try {
    await createSession();
  } catch (error) {
    const message = errorMessage(error);
    setStatus(message, "error");
    appendLog(`error: ${message}`);
  }
});

previewButton?.addEventListener("click", async () => {
  try {
    await startPreview();
  } catch (error) {
    const message = errorMessage(error);
    micEnabled = false;
    cameraEnabled = false;
    stopPreviewStream();
    syncMediaUi();
    setStatus(`media permission failed: ${message}`, "error");
    appendLog(`media permission failed: ${message}`);
  }
});

toggleMicButton?.addEventListener("click", toggleMic);
toggleCameraButton?.addEventListener("click", toggleCamera);
toggleContextDrawerButton?.addEventListener("click", toggleContextDrawer);
closeContextDrawerButton?.addEventListener("click", () => setContextDrawerOpen(false));

toggleSignalsBoxButton?.addEventListener("click", () => {
  if (!liveSignalsBody) {
    return;
  }
  const willShow = liveSignalsBody.hidden;
  liveSignalsBody.hidden = !willShow;
  toggleSignalsBoxButton.setAttribute("aria-expanded", String(willShow));
  toggleSignalsBoxButton.textContent = willShow ? "박스 접기" : "박스 펴기";
});
document.addEventListener("giljob:interviewer-question-started", () => {
  if (!micEnabled) {
    setAnswerTurnAvailability(false, "interviewer question started; answer button disabled");
  }
});
document.addEventListener("giljob:interviewer-question-ended", () => {
  setAnswerTurnAvailability(true, "interviewer question ended; answer button enabled");
});

form?.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await joinRoom();
  } catch (error) {
    const message = errorMessage(error);
    setRoomMode("prejoin");
    setStatus(message, "error");
    appendLog(`error: ${message}`);
    if (leaveButton) {
      leaveButton.disabled = true;
    }
    if (joinButton) {
      joinButton.disabled = false;
    }
  }
});

leaveButton?.addEventListener("click", leaveRoom);
window.addEventListener("pagehide", stopCaptionPolling);

renderSessionSummary(null);
renderAvatarState({ status: "pending", provider: "spatialreal", ready: false });
setContextDrawerOpen(false);
setRoomMode("prejoin");
setAnswerTurnAvailability(false);
syncMediaUi();
hydrateProductionRoutes();
renderTranscriptStatus("GilJobE analysis-engine 연결 후 답변 종료 시 전사가 표시됩니다.");
appendLog(`Interview Room ready for interview ${activeInterviewId}; use /api/sessions through Caddy for same-origin API access`);
autoJoinRoomRoute();
