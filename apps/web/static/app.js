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

let activeSession = null;
let activeRoom = null;
let localPreviewStream = null;
let micEnabled = false;
let cameraEnabled = false;
let answerTurnAvailable = false;
let nextQuestionRequested = false;
let currentTurnIndex = 1;
let lastAnswerTranscript = "";
let activeAnalysisSessionId = "";
let activeAvatarSession = null;
let avatarRtcRuntime = { sdkInitialized: false, player: null, view: null, provider: null, avatarId: "" };
let avatarRtcInitializing = null;
let answerTurnStartRecordCount = 0;
let activeRealtimeSession = null;
let realtimeAnswerTranscript = "";
let realtimeInterviewerQuestionTranscript = "";
let realtimeFirstAudioMarked = false;
let realtimeResponseInFlight = false;
let visionEventTimer = null;
const REALTIME_VISION_EVENT_MIN_INTERVAL_MS = 1500;
const REALTIME_VISION_EVENT_MAX_BYTES = 2048;
const REALTIME_TRANSCRIPT_COMPLETED_EVENT = "conversation.item.input_audio_transcription.completed";
const REALTIME_TRANSCRIPT_GRACE_MS = 6000;
const FULL_MMM_READY_MAX_ATTEMPTS = 30;
const REALTIME_INTERVIEWER_RESPONSE_INSTRUCTIONS = [
  "당신은 한국어 라이브 면접관입니다.",
  "백엔드 분석 준비는 이미 완료된 뒤에만 응답이 요청됩니다.",
  "후보자에게 MMM, sideband, backend, transcript, analysis-engine, internal gate 같은 내부 구현 단어를 절대 말하지 마세요.",
  "후보자가 질문/확인을 요청하면 먼저 짧게 답한 뒤, 직전 후보자 답변에 이어지는 자연스러운 면접 질문 하나만 하세요.",
  "한국어로 간결하게 말하세요."
].join(" ");
let realtimeTranscriptCompletionWaiters = [];
let realtimeTranscriptCompleted = false;
let realtimeTranscriptCompletionForward = Promise.resolve();
let realtimeAnswerFinishInFlight = false;
let realtimeTranscriptCompletedItemIds = new Set();
let answerTogglePointerDownAt = 0;
const activeInterviewId = interviewIdFromPath(window.location.pathname);
const shouldAutoJoinRoom = isProductionRoomPath(window.location.pathname);

function redactSensitiveText(value) {
  return String(value)
    .replace(/access_token=[^'"\s&]+/g, "access_token=<redacted>")
    .replace(/join_request=[^'"\s&]+/g, "join_request=<redacted>")
    .replace(/eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+/g, "<jwt-redacted>")
    .replace(/gj_(session|report)_[A-Za-z0-9._-]+/g, "gj_$1_<redacted>")
    .replace(/rt[a-zA-Z0-9_-]*_[A-Za-z0-9._-]+/g, "rt_<redacted>")
    .replace(/eph[_-][A-Za-z0-9._-]+/g, "eph_<redacted>");
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

function realtimeConfig(session = activeSession) {
  if (session === activeSession) {
    return activeSession?.realtime || activeSession?.openaiRealtime || null;
  }
  return session?.realtime || session?.openaiRealtime || null;
}

function defaultRealtimeSessionBrokerEndpoint() {
  return `/api/interviews/${encodeURIComponent(activeInterviewId)}/realtime/session`;
}

function isRealtimePrimary(session = activeSession) {
  const config = realtimeConfig(session);
  return Boolean(config?.enabled || config?.mode === "primary" || config?.transport === "webrtc");
}

function realtimeBrokerEndpoint(kind, session = activeSession) {
  const config = realtimeConfig(session) || {};
  if (kind === "session") {
    return config.sessionEndpoint || config.endpoints?.session || defaultRealtimeSessionBrokerEndpoint();
  }
  return config[`${kind}Endpoint`] || config.endpoints?.[kind] || null;
}

function realtimeTurnEventEndpoint(turnIndex = currentTurnIndex) {
  return `/api/interviews/${encodeURIComponent(activeInterviewId)}/turns/${turnIndex}/events`;
}

function realtimeVisionEventEndpoint(turnIndex = currentTurnIndex) {
  return `/api/interviews/${encodeURIComponent(activeInterviewId)}/turns/${turnIndex}/vision-events`;
}

async function postClientSafeJson(endpoint, body = {}) {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.message || payload.error || `request failed: HTTP ${response.status}`);
  }
  return payload;
}

function normalizedRealtimeEventKind(type) {
  return {
    "turn.answer.start": "turn.answer_started",
    "turn.answer.end": "turn.answer_ended",
    "analysis.transcript.delta": "transcript.delta",
    "analysis.transcript.completed": "transcript.completed",
    "analysis.vad.speech_started": "vad.speech_started",
    "analysis.vad.speech_stopped": "vad.speech_stopped",
    "prosody.window": "prosody.window_metrics",
    "analysis.prosody.window_metrics": "prosody.window_metrics",
  }[type] || null;
}

async function postRealtimeTurnEvent(type, detail = {}, turnIndex = currentTurnIndex) {
  if (!isRealtimePrimary()) {
    return null;
  }
  const normalizedType = normalizedRealtimeEventKind(type);
  const payload = {
    type,
    turnIndex,
    sessionId: analysisSessionId(),
    timestamp: new Date().toISOString(),
    detail,
  };
  if (normalizedType) {
    payload.normalizedType = normalizedType;
  }
  return postClientSafeJson(realtimeTurnEventEndpoint(turnIndex), payload);
}

function boundedVisionEvent(reason = "periodic", turnIndex = currentTurnIndex) {
  const video = candidateRoomVideo;
  const event = {
    type: "vision_metadata",
    normalizedType: "vision.frame_metrics",
    reason,
    turnIndex,
    capturedAt: new Date().toISOString(),
    source: "browser-camera-metadata",
    rawMediaIncluded: false,
    video: {
      cameraEnabled,
      width: Number(video?.videoWidth || 0),
      height: Number(video?.videoHeight || 0),
      readyState: Number(video?.readyState || 0),
    },
  };
  const encoded = JSON.stringify(event);
  if (encoded.length > REALTIME_VISION_EVENT_MAX_BYTES) {
    return {
      type: "vision_metadata",
      normalizedType: "vision.frame_metrics",
      reason,
      turnIndex,
      capturedAt: event.capturedAt,
      source: "browser-camera-metadata",
      rawMediaIncluded: false,
      truncated: true,
    };
  }
  return event;
}

async function sendBoundedVisionEvent(reason = "periodic", turnIndex = currentTurnIndex) {
  if (!isRealtimePrimary()) {
    return null;
  }
  const event = boundedVisionEvent(reason, turnIndex);
  try {
    await postClientSafeJson(realtimeVisionEventEndpoint(turnIndex), event);
    appendLog(`vision event sent: ${reason}; bounded metadata only; raw media hidden`);
  } catch (error) {
    appendLog(`vision event unavailable: ${errorMessage(error)}; full MMM must fail closed if visual state is required`);
  }
  return event;
}

function startVisionEventLoop() {
  stopVisionEventLoop();
  if (!isRealtimePrimary()) {
    return;
  }
  visionEventTimer = window.setInterval(() => {
    sendBoundedVisionEvent("periodic").catch((error) => appendLog(`vision event loop skipped: ${errorMessage(error)}`));
  }, REALTIME_VISION_EVENT_MIN_INTERVAL_MS);
}

function stopVisionEventLoop() {
  if (visionEventTimer) {
    window.clearInterval(visionEventTimer);
    visionEventTimer = null;
  }
}

async function requestRealtimeSessionBroker(session) {
  const payload = await postClientSafeJson(realtimeBrokerEndpoint("session", session), {
    interviewId: activeInterviewId,
    sessionId: session?.sessionId || activeInterviewId,
    role: "candidate",
    transport: "webrtc",
    turnDetection: "manual",
  });
  appendLog(`Realtime session broker ready; client secret hidden; session ${payload.sessionId || "issued"}`);
  return payload;
}

function realtimeClientSecretValue(brokerSession) {
  const clientSecret = brokerSession?.client_secret || brokerSession?.clientSecret;
  const value = typeof clientSecret === "string" ? clientSecret : clientSecret?.value;
  if (!value) {
    throw new Error("Realtime session broker did not return an ephemeral client secret");
  }
  return value;
}

function realtimeSdpEndpoint(session, brokerSession) {
  const configured = brokerSession?.webrtc?.sdpEndpoint || brokerSession?.sdpEndpoint || realtimeConfig(session)?.sdpEndpoint;
  if (configured) {
    return configured;
  }
  return "https://api.openai.com/v1/realtime/calls";
}

async function requestRealtimeWebrtcAnswer(session, offer, brokerSession) {
  const endpoint = realtimeSdpEndpoint(session, brokerSession);
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${realtimeClientSecretValue(brokerSession)}`,
      "Content-Type": "application/sdp",
    },
    body: offer.sdp,
  });
  const sdp = await response.text();
  if (!response.ok) {
    throw new Error(`Realtime WebRTC SDP attach failed: HTTP ${response.status}`);
  }
  if (!sdp.trim()) {
    throw new Error("Realtime WebRTC SDP attach returned an empty answer");
  }
  appendLog("Realtime WebRTC SDP attached with ephemeral client secret hidden; SDP hidden");
  return { type: "answer", sdp };
}

async function ensureRealtimeAudioStream() {
  if (activeRealtimeSession?.localStream) {
    activeRealtimeSession.localStream.getAudioTracks().forEach((track) => {
      track.enabled = micEnabled;
    });
    return activeRealtimeSession.localStream;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("browser media permissions are not available");
  }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  stream.getAudioTracks().forEach((track) => {
    track.enabled = micEnabled;
  });
  return stream;
}

function markRealtimeFirstAudio() {
  if (!realtimeResponseInFlight) {
    appendLog("Realtime remote audio track ready; first response audio not requested yet");
    return;
  }
  if (realtimeFirstAudioMarked) {
    return;
  }
  realtimeFirstAudioMarked = true;
  appendLog("realtime.first_audio marker emitted; audio hidden");
  postRealtimeTurnEvent("realtime.first_audio", { source: "remote-audio-track" }).catch((error) => appendLog(`first audio marker failed: ${errorMessage(error)}`));
}

function attachRealtimeRemoteAudio(stream) {
  if (!interviewerAudio) {
    return;
  }
  interviewerAudio.srcObject = stream;
  interviewerAudio.hidden = true;
  interviewerAudio.addEventListener("playing", markRealtimeFirstAudio, { once: true });
  interviewerAudio.play().catch((error) => appendLog(`Realtime remote audio autoplay skipped: ${errorMessage(error)}`));
}

function notifyRealtimeTranscriptCompleted() {
  const waiters = realtimeTranscriptCompletionWaiters;
  realtimeTranscriptCompletionWaiters = [];
  waiters.forEach((resolve) => resolve(true));
}

async function waitForRealtimeTranscriptCompletion(timeoutMs = REALTIME_TRANSCRIPT_GRACE_MS) {
  if (!realtimeTranscriptCompleted) {
    appendLog(`waiting for Realtime final transcript up to ${timeoutMs}ms before full MMM gate`);
    await new Promise((resolve) => {
      const done = (value) => {
        window.clearTimeout(timer);
        realtimeTranscriptCompletionWaiters = realtimeTranscriptCompletionWaiters.filter((fn) => fn !== done);
        resolve(Boolean(value));
      };
      const timer = window.setTimeout(() => done(false), timeoutMs);
      realtimeTranscriptCompletionWaiters.push(done);
    });
  }
  await realtimeTranscriptCompletionForward;
  return Boolean(realtimeTranscriptCompleted && realtimeAnswerTranscript.trim());
}

async function waitForRealtimeDataChannelOpen(channel, timeoutMs = 5000) {
  if (channel?.readyState === "open") {
    return;
  }
  await new Promise((resolve, reject) => {
    const cleanup = () => {
      window.clearTimeout(timer);
      channel?.removeEventListener("open", onOpen);
      channel?.removeEventListener("close", onClose);
      channel?.removeEventListener("error", onError);
    };
    const onOpen = () => {
      cleanup();
      resolve();
    };
    const onClose = () => {
      cleanup();
      reject(new Error("Realtime data channel closed before opening"));
    };
    const onError = () => {
      cleanup();
      reject(new Error("Realtime data channel failed before opening"));
    };
    const timer = window.setTimeout(() => {
      cleanup();
      reject(new Error("Realtime data channel open timed out"));
    }, timeoutMs);
    channel?.addEventListener("open", onOpen, { once: true });
    channel?.addEventListener("close", onClose, { once: true });
    channel?.addEventListener("error", onError, { once: true });
  });
}

async function sendRealtimeResponseCreate(reason = "manual") {
  const channel = activeRealtimeSession?.dataChannel;
  if (!channel || channel.readyState !== "open") {
    throw new Error("Realtime data channel is not open");
  }
  realtimeFirstAudioMarked = false;
  realtimeResponseInFlight = true;
  realtimeInterviewerQuestionTranscript = "";
  channel.send(JSON.stringify({
    type: "response.create",
    response: {
      output_modalities: ["audio"],
      instructions: REALTIME_INTERVIEWER_RESPONSE_INSTRUCTIONS,
    },
  }));
  await postRealtimeTurnEvent("realtime.response.create", { reason });
  appendLog(`realtime.response.create sent after gate: ${reason}; internal analysis ready; internal terms hidden from prompt`);
}

function extractRealtimeInputTranscript(event) {
  if (typeof event?.transcript === "string") {
    return event.transcript.trim();
  }
  return "";
}

function sendRealtimeTranscriptToConversation(transcript) {
  const channel = activeRealtimeSession?.dataChannel;
  const text = String(transcript || "").trim();
  if (!channel || channel.readyState !== "open" || !text) {
    return false;
  }
  channel.send(JSON.stringify({
    type: "conversation.item.create",
    item: {
      type: "message",
      role: "user",
      content: [{ type: "input_text", text }],
    },
  }));
  appendLog(`Realtime transcript injected into conversation context; chars ${text.length}; raw hidden`);
  return true;
}

function handleRealtimeServerEvent(event) {
  const type = String(event?.type || "unknown");
  if (type === "conversation.item.input_audio_transcription.delta" && typeof event.delta === "string") {
    realtimeAnswerTranscript = `${realtimeAnswerTranscript}${event.delta}`.trim();
    postRealtimeTurnEvent("analysis.transcript.delta", { transcript: event.delta, itemId: event.item_id || "unknown" }).catch((error) => appendLog(`transcript event forward failed: ${errorMessage(error)}`));
    renderTranscriptStatus("Realtime transcript delta received. Raw transcript is not written to logs.");
    return;
  }
  if (type === "conversation.item.input_audio_transcription.completed" || type === "conversation.item.input_audio_transcription.done") {
    const transcript = extractRealtimeInputTranscript(event);
    const itemId = String(event.item_id || event.item?.id || "unknown");
    const dedupeKey = `${itemId}:${transcript}`;
    if (!transcript || realtimeTranscriptCompletedItemIds.has(dedupeKey)) {
      return;
    }
    realtimeTranscriptCompletedItemIds.add(dedupeKey);
    realtimeAnswerTranscript = transcript || realtimeAnswerTranscript;
    realtimeTranscriptCompleted = true;
    realtimeTranscriptCompletionForward = (async () => {
      try {
        await postRealtimeTurnEvent("analysis.transcript.completed", { transcript, itemId });
        appendLog(`Realtime transcript completion forwarded; chars ${transcript.length}; raw hidden`);
      } catch (error) {
        appendLog(`transcript completion forward failed: ${errorMessage(error)}`);
      }
      sendRealtimeTranscriptToConversation(transcript);
    })();
    renderTranscriptStatus(`Realtime 전사 완료 (${transcript.length} chars). Raw transcript is not written to logs.`);
    realtimeTranscriptCompletionForward.finally(() => notifyRealtimeTranscriptCompleted());
    return;
  }
  if (type === "input_audio_buffer.speech_started") {
    postRealtimeTurnEvent("analysis.vad.speech_started", { itemId: event.item_id || "unknown", audioStartMs: Number(event.audio_start_ms || 0), rawAudioIncluded: false }).catch((error) => appendLog(`VAD start forward failed: ${errorMessage(error)}`));
    appendLog("Realtime VAD speech started; raw audio hidden");
    return;
  }
  if (type === "input_audio_buffer.speech_stopped") {
    postRealtimeTurnEvent("analysis.vad.speech_stopped", { itemId: event.item_id || "unknown", audioEndMs: Number(event.audio_end_ms || 0), rawAudioIncluded: false }).catch((error) => appendLog(`VAD stop forward failed: ${errorMessage(error)}`));
    postRealtimeTurnEvent("analysis.prosody.window_metrics", { itemId: event.item_id || "unknown", source: "realtime-audio-lifecycle", rawAudioIncluded: false }).catch((error) => appendLog(`prosody lifecycle forward failed: ${errorMessage(error)}`));
    appendLog("Realtime VAD speech stopped; prosody lifecycle marker sent; raw audio hidden");
    return;
  }
  if (type === "response.audio_transcript.delta" || type === "response.output_audio_transcript.delta") {
    if (typeof event.delta === "string") {
      realtimeInterviewerQuestionTranscript = `${realtimeInterviewerQuestionTranscript}${event.delta}`.trim();
      renderRealtimeQuestionProgress();
    }
    markRealtimeFirstAudio();
    return;
  }
  if (type === "response.audio_transcript.done" || type === "response.output_audio_transcript.done") {
    const transcript = extractRealtimeOutputTranscript(event);
    if (transcript) {
      realtimeInterviewerQuestionTranscript = transcript;
      renderRealtimeQuestionProgress();
    }
    markRealtimeFirstAudio();
    return;
  }
  if (type === "response.audio.delta" || type === "response.output_audio.delta") {
    renderRealtimeQuestionProgress();
    markRealtimeFirstAudio();
    return;
  }
  if (type === "response.done") {
    renderRealtimeQuestionDone(event);
    realtimeResponseInFlight = false;
    markInterviewerQuestionEnded({ provider: "openai-realtime", turnIndex: currentTurnIndex });
  }
}

function bindRealtimeDataChannel(channel) {
  channel.addEventListener("open", () => {
    appendLog("Realtime data channel open; browser tools disabled; backend sideband required");
  });
  channel.addEventListener("message", (event) => {
    try {
      handleRealtimeServerEvent(JSON.parse(event.data));
    } catch (error) {
      appendLog(`Realtime event ignored: ${errorMessage(error)}`);
    }
  });
  channel.addEventListener("close", () => appendLog("Realtime data channel closed"));
}

async function sendRealtimeProsodyEvent(reason = "window", turnIndex = currentTurnIndex) {
  return postRealtimeTurnEvent("prosody.window", {
    reason,
    source: "browser-audio-window-metadata",
    rawMediaIncluded: false,
    rawAudioIncluded: false,
  }, turnIndex);
}

async function waitForFullMmmReady(turnIndex) {
  const endpoint = `/api/interviews/${encodeURIComponent(activeInterviewId)}/turns/${turnIndex}/mmm-ready`;
  for (let attempt = 0; attempt < FULL_MMM_READY_MAX_ATTEMPTS; attempt += 1) {
    const response = await fetch(endpoint, { headers: { Accept: "application/json" } });
    const payload = await response.json().catch(() => ({}));
    if (response.ok && payload.full_mmm_ready === true) {
      await postRealtimeTurnEvent("analysis.full_mmm.ready", { ready: true, source: "api" }, turnIndex);
      appendLog(`full_mmm_ready received for turn ${turnIndex}; next Realtime audio allowed`);
      return payload;
    }
    if (response.ok && (payload.degraded === true || payload.ready === false)) {
      appendLog(`full MMM not ready for turn ${turnIndex}: ${payload.reason || "degraded"}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("full_mmm_ready gate timed out; ordinary next-question audio blocked");
}

async function requestRealtimeNextQuestion(reason = "manual") {
  if (nextQuestionRequested) {
    return;
  }
  nextQuestionRequested = true;
  document.dispatchEvent(new CustomEvent("giljob:interviewer-question-started"));
  renderQuestionLoading();
  if (currentTurnIndex > 1) {
    await waitForFullMmmReady(currentTurnIndex - 1);
  }
  await sendRealtimeResponseCreate(reason);
}

async function connectRealtimeRoom(session) {
  setRoomMode("connecting");
  setStatus("connecting to OpenAI Realtime WebRTC...", "connecting");
  const brokerSession = await requestRealtimeSessionBroker(session);
  const peerConnection = new RTCPeerConnection();
  const dataChannel = peerConnection.createDataChannel("oai-events");
  bindRealtimeDataChannel(dataChannel);
  const remoteStream = new MediaStream();
  peerConnection.addEventListener("track", (event) => {
    remoteStream.addTrack(event.track);
    attachRealtimeRemoteAudio(remoteStream);
  });
  const localStream = await ensureRealtimeAudioStream();
  localStream.getAudioTracks().forEach((track) => peerConnection.addTrack(track, localStream));
  peerConnection.addTransceiver("audio", { direction: "recvonly" });
  activeRealtimeSession = { peerConnection, dataChannel, localStream, brokerSession };
  const offer = await peerConnection.createOffer();
  await peerConnection.setLocalDescription(offer);
  const answer = await requestRealtimeWebrtcAnswer(session, offer, brokerSession);
  await peerConnection.setRemoteDescription(answer);
  setRoomMode("connected");
  setStatus("Realtime connected", "connected");
  if (leaveButton) {
    leaveButton.disabled = false;
  }
  if (joinButton) {
    joinButton.disabled = true;
  }
  startVisionEventLoop();
  appendLog("Realtime WebRTC connected; OpenAI standard API key stays server-side");
  await waitForRealtimeDataChannelOpen(dataChannel);
  nextQuestionRequested = false;
  await requestRealtimeNextQuestion("realtime-connected");
}

async function applyRealtimeMediaState() {
  if (!activeRealtimeSession?.localStream) {
    return;
  }
  activeRealtimeSession.localStream.getAudioTracks().forEach((track) => {
    track.enabled = micEnabled;
  });
  appendLog(`Realtime media updated: answer ${micEnabled ? "recording" : "ended"}; camera metadata ${cameraEnabled ? "enabled" : "disabled"}`);
}

async function disconnectRealtimeRoom() {
  stopVisionEventLoop();
  const session = activeRealtimeSession;
  activeRealtimeSession = null;
  if (!session) {
    return;
  }
  session.dataChannel?.close();
  session.peerConnection?.close();
  session.localStream?.getTracks().forEach((track) => track.stop());
  if (interviewerAudio) {
    interviewerAudio.srcObject = null;
  }
  appendLog("leaving Realtime WebRTC room; secrets hidden");
}

async function finishRealtimeAnswerAndRequestNextQuestion() {
  if (realtimeAnswerFinishInFlight) {
    appendLog("answer finish already in progress; duplicate click ignored");
    return;
  }
  realtimeAnswerFinishInFlight = true;
  try {
    const completedTurnIndex = currentTurnIndex;
    micEnabled = false;
    setAnswerTurnAvailability(false, "candidate answer ending; waiting for transcript/MMM gate");
    await restartPreviewStream();
    await applyRealtimeMediaState();
    const transcriptReady = await waitForRealtimeTranscriptCompletion();
    if (!transcriptReady) {
      renderTranscriptStatus("Realtime 전사 결과가 없습니다. 마이크 입력/브라우저 권한/무음 상태를 확인한 뒤 다시 답변해 주세요.");
      setAnswerTurnAvailability(true, "candidate answer ended without transcript; next question blocked for retry");
      throw new Error("Realtime transcript unavailable; next question blocked");
    }
    await postRealtimeTurnEvent("turn.answer.end", { transcriptAvailable: transcriptReady }, completedTurnIndex);
    await sendBoundedVisionEvent("answer_end", completedTurnIndex);
    await sendRealtimeProsodyEvent("answer_end", completedTurnIndex);
    lastAnswerTranscript = realtimeAnswerTranscript || "Realtime transcript unavailable.";
    realtimeAnswerTranscript = "";
    realtimeTranscriptCompleted = false;
    renderTranscriptStatus("답변 종료. full MMM 준비 신호를 기다리는 중입니다.");
    await waitForFullMmmReady(completedTurnIndex);
    currentTurnIndex += 1;
    nextQuestionRequested = false;
    setAnswerTurnAvailability(false, "candidate answer ended; full MMM gate passed; waiting for next Realtime question");
    await requestRealtimeNextQuestion("candidate-answer-ended-full-mmm-ready");
  } finally {
    realtimeAnswerFinishInFlight = false;
  }
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

function muteAvatarRtcAudioElements() {
  const scope = avatarRenderTarget || avatarSurface || document;
  scope.querySelectorAll?.("audio, video").forEach((element) => {
    if (element !== interviewerAudio) {
      element.muted = true;
      element.volume = 0;
    }
  });
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
        muteAvatarRtcAudioElements();
        appendLog("avatar rtc connected through LiveKit; tokens hidden; Avatar RTC media muted to avoid dual-audio drift with OpenAI Realtime output");
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

function extractRealtimeOutputTranscript(event) {
  const direct = typeof event?.transcript === "string" ? event.transcript : "";
  if (direct.trim()) {
    return direct.trim();
  }
  const output = Array.isArray(event?.response?.output) ? event.response.output : [];
  const chunks = [];
  output.forEach((item) => {
    const content = Array.isArray(item?.content) ? item.content : [];
    content.forEach((part) => {
      if (typeof part?.transcript === "string" && part.transcript.trim()) {
        chunks.push(part.transcript.trim());
      }
      if (typeof part?.text === "string" && part.text.trim()) {
        chunks.push(part.text.trim());
      }
    });
  });
  return chunks.join(" ").trim();
}

function renderRealtimeQuestionProgress() {
  const text = realtimeInterviewerQuestionTranscript.trim() || "Realtime 음성 질문을 재생하고 있습니다.";
  if (currentQuestionTitle) {
    currentQuestionTitle.textContent = `질문 ${currentTurnIndex}`;
  }
  if (currentQuestionBody) {
    currentQuestionBody.textContent = text;
  }
  if (interviewerQuestionText) {
    interviewerQuestionText.textContent = text;
  }
  if (interviewerMediaState) {
    interviewerMediaState.textContent = "질문 재생 중";
  }
  if (avatarSurface && activeAvatarSession?.ready) {
    avatarSurface.dataset.state = "speaking";
  }
  muteAvatarRtcAudioElements();
}

function renderRealtimeQuestionDone(event) {
  const extracted = extractRealtimeOutputTranscript(event);
  if (extracted) {
    realtimeInterviewerQuestionTranscript = extracted;
  }
  const question = realtimeInterviewerQuestionTranscript.trim() || "Realtime 음성 질문 재생이 완료되었습니다.";
  renderInterviewQuestion({
    question,
    questionId: `realtime-${currentTurnIndex}`,
    turnIndex: currentTurnIndex,
    provider: "openai-realtime",
  });
  realtimeInterviewerQuestionTranscript = "";
}

function renderQuestionLoading() {
  if (currentQuestionTitle) {
    currentQuestionTitle.textContent = "질문 생성 중";
  }
  if (currentQuestionBody) {
    currentQuestionBody.textContent = isRealtimePrimary()
      ? "Realtime sideband가 full MMM 준비 이후 다음 질문을 발화합니다."
      : "Gemini 기반 InterviewController가 다음 질문을 생성하고 있습니다.";
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
  if (isRealtimePrimary() && activeRealtimeSession) {
    return requestRealtimeNextQuestion(reason);
  }
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
  if (activeRealtimeSession) {
    await applyRealtimeMediaState();
    return;
  }
  if (!activeRoom) {
    return;
  }
  await activeRoom.localParticipant.setMicrophoneEnabled(micEnabled);
  await activeRoom.localParticipant.setCameraEnabled(cameraEnabled);
  appendLog(`room media updated: answer ${micEnabled ? "recording" : "ended"}, camera ${cameraEnabled ? "on" : "off"}`);
}

async function startAnswerCapture() {
  if (activeRealtimeSession) {
    realtimeAnswerTranscript = "";
    realtimeTranscriptCompleted = false;
    realtimeTranscriptCompletionForward = Promise.resolve();
    realtimeTranscriptCompletedItemIds = new Set();
    await postRealtimeTurnEvent("turn.answer.start", { source: "browser-manual-button" });
    await sendBoundedVisionEvent("answer_start");
    await sendRealtimeProsodyEvent("answer_start");
    renderTranscriptStatus("답변 중입니다. Realtime STT/VAD 이벤트와 bounded vision metadata를 analysis-engine으로 전달합니다.");
    appendLog("candidate answer turn started; Realtime event boundary active; raw transcript hidden");
    return;
  }
  await markAnalysisTurnStart(analysisSessionId());
  renderTranscriptStatus("답변 중입니다. GilJobE analysis-engine이 LiveKit 오디오를 수집하고 있습니다.");
  appendLog("candidate answer turn started; GilJobE analysis-engine recording boundary active");
}

async function finishAnswerAndRequestNextQuestion() {
  if (activeRealtimeSession) {
    await finishRealtimeAnswerAndRequestNextQuestion();
    return;
  }
  micEnabled = false;
  await restartPreviewStream();
  await applyMediaStateToRoom();
  const sessionId = analysisSessionId();
  renderTranscriptStatus("답변 종료. GilJobE analysis-engine에서 최종 전사를 가져오는 중입니다.");
  const transcript = await flushAnalysisTurn(sessionId);
  lastAnswerTranscript = transcript || "전사 결과가 비어 있습니다.";
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
    stopPreviewStream();
    syncMediaUi();
    setStatus(`answer turn failed: ${message}`, "error");
    appendLog(`answer turn failed: ${message}`);
  }
}

function rememberAnswerTogglePointerDown(event) {
  if (event?.isTrusted === true && event.button === 0) {
    answerTogglePointerDownAt = Date.now();
  }
}

function handleToggleMicClick(event) {
  const pointerAgeMs = Date.now() - answerTogglePointerDownAt;
  if (event?.isTrusted !== true || pointerAgeMs < 0 || pointerAgeMs > 1500) {
    appendLog("answer toggle ignored: missing recent pointerdown or untrusted event");
    return;
  }
  answerTogglePointerDownAt = 0;
  appendLog(`answer toggle accepted: user pointer event detail ${Number(event.detail || 0)}`);
  toggleMic();
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
  if (isRealtimePrimary(session)) {
    await connectRealtimeRoom(session);
    return;
  }
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
  if (activeRealtimeSession) {
    disconnectAvatarRtc();
    disconnectRealtimeRoom();
    setRoomMode("prejoin");
    setStatus("Realtime disconnected", "idle");
    if (leaveButton) {
      leaveButton.disabled = true;
    }
    if (joinButton) {
      joinButton.disabled = false;
    }
    return;
  }
  if (!activeRoom) {
    return;
  }
  appendLog("leaving LiveKit room");
  disconnectAvatarRtc();
  activeRoom.disconnect();
  activeRoom = null;
  if (leaveButton) {
    leaveButton.disabled = true;
  }
  if (joinButton) {
    joinButton.disabled = false;
  }
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

toggleMicButton?.addEventListener("pointerdown", rememberAnswerTogglePointerDown);
toggleMicButton?.addEventListener("click", handleToggleMicClick);
toggleCameraButton?.addEventListener("click", toggleCamera);
toggleContextDrawerButton?.addEventListener("click", toggleContextDrawer);
closeContextDrawerButton?.addEventListener("click", () => setContextDrawerOpen(false));
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
