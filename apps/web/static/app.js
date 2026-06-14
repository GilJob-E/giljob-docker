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
const coachFeedbackTitle = document.querySelector("#coach-feedback-title");
const coachFeedbackBody = document.querySelector("#coach-feedback-body");
const coachFeedbackList = document.querySelector("#coach-feedback-list");
const mmmDebugSummary = document.querySelector("#mmm-debug-summary");

let activeSession = null;
let localPreviewStream = null;
let micEnabled = false;
let cameraEnabled = false;
let answerTurnAvailable = false;
let nextQuestionRequested = false;
let currentTurnIndex = 1;
let lastAnswerTranscript = "";
let lastAnalysisBlock = ""; // server-owned analysis summary only; browser never starts analysis workers or injects verbatim transcripts.
let activeAvatarSession = null;
let avatarSdkModeState = { initialized: false, outcome: "sdk_mode_deferred", reason: "not_started", audioFeed: "pcm16-mono-16000" };
let activeRealtimeSession = null;
let realtimeRemoteAudioTrack = null;
let activeAvatarSdkRuntime = null;
let avatarSdkInitializePromise = null;
let avatarPcmBridge = null;
let avatarPcmBridgeIdleTimer = null;
let avatarPcmBridgeEndTimer = null;
let avatarSdkResponseFeedActive = false;
let avatarSdkSyncedPlaybackActive = false;
let avatarSdkConnectionState = "unknown";
let avatarSdkConnectionWaiters = [];
let avatarSdkPcmStats = { chunks: 0, bytes: 0, sends: 0, nullSends: 0, silentDrops: 0, rmsMax: 0, startedAt: 0, lastChunkAt: 0, lastSpeechAt: 0, responseDoneAt: 0, speechStarted: false };
let activeRealtimeResponseId = "";
let realtimeAnswerTranscript = "";
let realtimeInterviewerQuestionTranscript = "";
let realtimeFirstAudioMarked = false;
let realtimeResponseInFlight = false;
let visionEventTimer = null;
const REALTIME_VISION_EVENT_MIN_INTERVAL_MS = 1500;
const REALTIME_VISION_EVENT_MAX_BYTES = 48000;
const REALTIME_VISION_FRAME_MAX_BYTES = 36000;
const REALTIME_VISION_FRAME_WIDTH = 160;
const REALTIME_VISION_FRAME_QUALITY = 0.45;
const REALTIME_TRANSCRIPT_COMPLETED_EVENT = "conversation.item.input_audio_transcription.completed";
const REALTIME_TRANSCRIPT_GRACE_MS = 6000;
const FULL_MMM_READY_MAX_ATTEMPTS = 30;
const SPATIALREAL_SDK_MODE_WEB_ENABLED = "SPATIALREAL_SDK_MODE_WEB_ENABLED";
const SPATIALREAL_SDK_READY_OUTCOME = "sdk_mode_ready";
const SPATIALREAL_SDK_DEFERRED_OUTCOME = "sdk_mode_deferred";
const SPATIALREAL_SDK_ACCEPTED_OUTCOMES = new Set([SPATIALREAL_SDK_READY_OUTCOME, "sdk_mode_verified"]);
const SPATIALREAL_SDK_MODE = "spatialreal-sdk-mode-web";
const SPATIALREAL_SDK_TRANSPORT = "spatialreal-sdk-websocket";
const SPATIALREAL_SDK_AUDIO_FEED_FORMAT = "pcm16-mono-16000";
const AVATAR_PCM_END_GRACE_MS = 3000;
const AVATAR_PCM_TAIL_SILENCE_MS = 2200;
const AVATAR_PCM_MAX_DRAIN_MS = 20000;
const AVATAR_PCM_NO_SPEECH_DRAIN_MS = 8000;
const AVATAR_PCM_TAIL_POLL_MS = 250;
const AVATAR_PCM_SPEECH_RMS_THRESHOLD = 0.0015;
const AVATAR_SDK_CONNECTED_WAIT_MS = 5000;
const AVATAR_SDK_SYNCED_PLAYBACK_VOLUME = 1;
const LIVEKIT_FREE_REALTIME_MAIN_PATH_LABEL = "LiveKit-free Realtime main path";
const AVATAR_DEFERRED_LABEL = "Avatar disabled/deferred";
const SPATIALREAL_SDK_MODE_LABEL = "SpatialReal SDK Mode";
const SPATIALREAL_SDK_SAFE_BLOCKED_REASONS = [
  "sdk_flag_disabled",
  "spatialreal_config_missing",
  "sdk_mode_blocked_missing_vendor_asset",
  "sdk_mode_blocked_wasm_mime",
  "sdk_mode_blocked_dynamic_import",
  "sdk_mode_blocked_double_audio_or_mute",
  "sdk_mode_blocked_pcm_feed_setup_failed",
  "sdk_mode_blocked_pcm_send_failed",
];
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
  const timestamp = new Date().toISOString();
  const safeMessage = redactSensitiveText(message);
  if (logEl) {
    logEl.textContent = `${timestamp} ${safeMessage}\n${logEl.textContent}`;
  }
  const lowerMessage = String(safeMessage).toLowerCase();
  if ((lowerMessage.includes("avatar sdk") || lowerMessage.includes("spatialreal sdk")) && window.console?.info) {
    window.console.info(`[giljob-avatar] ${timestamp} ${safeMessage}`);
  }
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

function avatarSdkModeConfig(payload = activeAvatarSession) {
  // SDK Mode metadata must be sibling/public metadata. Prefer API-owned
  // avatarSdk/client.spatialrealSdk metadata over legacy bridge shapes.
  const clientSdk = payload?.client?.spatialrealSdk && typeof payload.client.spatialrealSdk === "object" ? payload.client.spatialrealSdk : {};
  return payload?.sdkMode || payload?.avatarSdk || clientSdk.sdkMode || clientSdk || activeSession?.avatarSdk || activeSession?.avatarSdkMode || {};
}

function avatarSdkAudioFeedConfig(payload = activeAvatarSession) {
  const sdkMode = avatarSdkModeConfig(payload);
  return sdkMode.audioFeed || sdkMode.audio || {};
}

function normalizeAvatarSdkModeState(payload = activeAvatarSession) {
  const sdkMode = avatarSdkModeConfig(payload);
  const audioFeed = avatarSdkAudioFeedConfig(payload);
  const audioFormat = audioFeed.format || [audioFeed.encoding, audioFeed.channels, audioFeed.sampleRate].filter(Boolean).join("-") || SPATIALREAL_SDK_AUDIO_FEED_FORMAT;
  const metadataAccepted = sdkMode.enabled === true
    && sdkMode.mode === SPATIALREAL_SDK_MODE
    && [SPATIALREAL_SDK_TRANSPORT, "spatialreal-sdk-websocket"].includes(sdkMode.transport)
    && sdkMode.livekitRequired === false
    && sdkMode.requiresFeatureFlag === SPATIALREAL_SDK_MODE_WEB_ENABLED
    && SPATIALREAL_SDK_ACCEPTED_OUTCOMES.has(sdkMode.outcome || sdkMode.status)
    && sdkMode.providerSecretsExposed === false
    && sdkMode.rawMediaExposed === false
    && sdkMode.rawTranscriptExposed !== true;
  return {
    initialized: false,
    metadataAccepted,
    mode: sdkMode.mode || SPATIALREAL_SDK_MODE,
    transport: sdkMode.transport || SPATIALREAL_SDK_TRANSPORT,
    livekitRequired: sdkMode.livekitRequired === false ? false : Boolean(sdkMode.livekitRequired),
    outcome: sdkMode.outcome || sdkMode.status || SPATIALREAL_SDK_DEFERRED_OUTCOME,
    reason: sdkMode.reason || (metadataAccepted ? "pcm_audio_feed_unverified" : "sdk_mode_metadata_incomplete"),
    audioFeed: audioFormat || SPATIALREAL_SDK_AUDIO_FEED_FORMAT,
  };
}

function isSpatialRealSdkModeEnabled(payload = activeAvatarSession) {
  return normalizeAvatarSdkModeState(payload).metadataAccepted === true;
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

function realtimeCallEndpoint(session = activeSession) {
  const config = realtimeConfig(session) || {};
  return config.callEndpoint || config.endpoints?.call || `/api/interviews/${encodeURIComponent(activeInterviewId)}/realtime/call`;
}

function realtimeResponseEndpoint(turnIndex = currentTurnIndex, session = activeSession) {
  const config = realtimeConfig(session) || {};
  const template = config.responseCreateEndpoint || config.responseEndpoint || config.endpoints?.responseCreate || config.endpoints?.response;
  if (template) {
    return String(template).replace("{turnIndex}", encodeURIComponent(turnIndex));
  }
  return `/api/interviews/${encodeURIComponent(activeInterviewId)}/turns/${turnIndex}/realtime/response`;
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

function visionVideoMetrics(video = candidateRoomVideo) {
  return {
    cameraEnabled,
    width: Number(video?.videoWidth || 0),
    height: Number(video?.videoHeight || 0),
    readyState: Number(video?.readyState || 0),
  };
}

function canvasBlob(canvas, type, quality) {
  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob), type, quality);
  });
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || "");
      resolve(value.includes(",") ? value.split(",").pop() : value);
    };
    reader.onerror = () => reject(reader.error || new Error("vision frame encode failed"));
    reader.readAsDataURL(blob);
  });
}

async function captureInternalVisionFrame(video = candidateRoomVideo) {
  const metrics = visionVideoMetrics(video);
  if (!cameraEnabled || !video || metrics.readyState < 2 || metrics.width <= 0 || metrics.height <= 0) {
    return {
      signals: {
        frameAvailable: false,
        cameraEnabled,
        visualQuality: cameraEnabled ? "camera_not_ready" : "camera_off",
      },
      frame: null,
    };
  }

  const width = Math.min(REALTIME_VISION_FRAME_WIDTH, metrics.width);
  const height = Math.max(1, Math.round((metrics.height / metrics.width) * width));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) {
    return { signals: { frameAvailable: false, visualQuality: "canvas_unavailable" }, frame: null };
  }
  context.drawImage(video, 0, 0, width, height);

  let averageLuma = null;
  let darkPixelRatio = null;
  try {
    const pixels = context.getImageData(0, 0, width, height).data;
    let lumaTotal = 0;
    let darkPixels = 0;
    for (let index = 0; index < pixels.length; index += 4) {
      const luma = (0.2126 * pixels[index]) + (0.7152 * pixels[index + 1]) + (0.0722 * pixels[index + 2]);
      lumaTotal += luma;
      if (luma < 35) {
        darkPixels += 1;
      }
    }
    const pixelCount = pixels.length / 4;
    averageLuma = Number((lumaTotal / Math.max(1, pixelCount)).toFixed(1));
    darkPixelRatio = Number((darkPixels / Math.max(1, pixelCount)).toFixed(3));
  } catch (_error) {
    averageLuma = null;
    darkPixelRatio = null;
  }

  const blob = await canvasBlob(canvas, "image/jpeg", REALTIME_VISION_FRAME_QUALITY);
  if (!blob || blob.size <= 0 || blob.size > REALTIME_VISION_FRAME_MAX_BYTES) {
    return {
      signals: {
        frameAvailable: false,
        frameDroppedReason: blob && blob.size > REALTIME_VISION_FRAME_MAX_BYTES ? "encoded_frame_too_large" : "encode_failed",
        visualQuality: "frame_unavailable",
        averageLuma,
        darkPixelRatio,
      },
      frame: null,
    };
  }

  const data = await blobToBase64(blob);
  return {
    signals: {
      frameAvailable: true,
      cameraEnabled,
      width,
      height,
      averageLuma,
      darkPixelRatio,
      visualQuality: averageLuma === null ? "unknown" : (averageLuma < 35 ? "too_dark" : "usable"),
      faceVisible: null,
    },
    frame: {
      schemaVersion: "2026-06-13.internal-vision-frame.v1",
      internalOnly: true,
      notLogged: true,
      encoding: "image/jpeg;base64",
      width,
      height,
      byteLength: blob.size,
      data,
    },
  };
}

async function boundedVisionEvent(reason = "periodic", turnIndex = currentTurnIndex) {
  const video = candidateRoomVideo;
  const metrics = visionVideoMetrics(video);
  const capture = await captureInternalVisionFrame(video);
  const event = {
    type: "vision_metadata",
    normalizedType: "vision.frame_metrics",
    reason,
    turnIndex,
    capturedAt: new Date().toISOString(),
    source: "browser-camera-sideband",
    rawMediaIncluded: false,
    internalVisionFrameIncluded: Boolean(capture.frame),
    video: metrics,
    detail: {
      schemaVersion: "2026-06-13.realtime-vision-sideband.v1",
      cameraEnabled: metrics.cameraEnabled,
      width: metrics.width,
      height: metrics.height,
      readyState: metrics.readyState,
      visionSignals: capture.signals,
      ...(capture.frame ? { visionFrame: capture.frame } : {}),
    },
  };
  if (JSON.stringify(event).length > REALTIME_VISION_EVENT_MAX_BYTES) {
    delete event.detail.visionFrame;
    event.internalVisionFrameIncluded = false;
    event.detail.visionSignals = {
      ...event.detail.visionSignals,
      frameAvailable: false,
      frameDroppedReason: "event_too_large",
    };
  }
  if (JSON.stringify(event).length > REALTIME_VISION_EVENT_MAX_BYTES) {
    return {
      type: "vision_metadata",
      normalizedType: "vision.frame_metrics",
      reason,
      turnIndex,
      capturedAt: event.capturedAt,
      source: "browser-camera-sideband",
      rawMediaIncluded: false,
      internalVisionFrameIncluded: false,
      truncated: true,
      detail: {
        schemaVersion: "2026-06-13.realtime-vision-sideband.v1",
        visionSignals: {
          frameAvailable: false,
          frameDroppedReason: "event_too_large",
          cameraEnabled: metrics.cameraEnabled,
        },
      },
    };
  }
  return event;
}

async function sendBoundedVisionEvent(reason = "periodic", turnIndex = currentTurnIndex) {
  if (!isRealtimePrimary()) {
    return null;
  }
  const event = await boundedVisionEvent(reason, turnIndex);
  try {
    await postClientSafeJson(realtimeVisionEventEndpoint(turnIndex), event);
    appendLog(`vision event sent: ${reason}; ${event.internalVisionFrameIncluded ? "internal frame sampled" : "metadata/signals only"}; raw media not logged`);
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
  appendLog(`Realtime session broker ready; provider secrets hidden; session ${payload.sessionId || payload.id || "issued"}`);
  return payload;
}

async function requestRealtimeWebrtcAnswer(session, offer, brokerSession) {
  const endpoint = realtimeCallEndpoint(session);
  const payload = await postClientSafeJson(endpoint, {
    sdp: offer.sdp,
    sessionId: brokerSession?.sessionId || brokerSession?.id || analysisSessionId(),
    model: brokerSession?.model,
    voice: brokerSession?.voice,
  });
  const answer = payload?.sdpAnswer || payload?.answer || null;
  const sdp = typeof answer === "string" ? answer : answer?.sdp;
  if (!sdp || !String(sdp).trim()) {
    throw new Error("Realtime API call broker did not return an SDP answer; browser direct provider attach is disabled");
  }
  appendLog("Realtime WebRTC SDP attached through API call broker; standard key/SDP hidden from logs");
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

function setRealtimeDirectAudioOutputMutedForAvatar(isMuted, reason = "avatar-sync") {
  const nextMuted = Boolean(isMuted);
  const changed = avatarSdkSyncedPlaybackActive !== nextMuted;
  avatarSdkSyncedPlaybackActive = nextMuted;
  if (interviewerAudio) {
    interviewerAudio.muted = nextMuted;
    interviewerAudio.volume = nextMuted ? 0 : 1;
  }
  if (changed) {
    appendLog(`Realtime direct audio output ${nextMuted ? "muted" : "audible"}; reason=${String(reason).replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 80)}; ${nextMuted ? "SpatialReal SDK synced playback is audible" : "Realtime direct audio is audible fallback"}; media hidden`);
  }
}

function attachRealtimeRemoteAudio(stream) {
  if (!interviewerAudio) {
    return;
  }
  interviewerAudio.srcObject = stream;
  interviewerAudio.hidden = true;
  setRealtimeDirectAudioOutputMutedForAvatar(avatarSdkSyncedPlaybackActive, "attach-realtime-remote-audio");
  interviewerAudio.addEventListener("playing", markRealtimeFirstAudio, { once: true });
  interviewerAudio.play().catch((error) => appendLog(`Realtime remote audio autoplay skipped: ${errorMessage(error)}`));
}


function avatarSdkClientMetadata(payload = activeAvatarSession) {
  const client = payload?.client && typeof payload.client === "object" ? payload.client : {};
  const clientSdk = client.spatialrealSdk && typeof client.spatialrealSdk === "object" ? client.spatialrealSdk : {};
  const sdkMode = avatarSdkModeConfig(payload);
  const audioFormat = payload?.audioFormat || sdkMode.audioFormat || sdkMode.audio || clientSdk.audioFormat || client.audioFormat || {};
  return {
    appId: payload?.appId || sdkMode.appId || clientSdk.appId || client.appId || activeSession?.avatarSdk?.appId || "",
    sessionToken: payload?.sessionToken || sdkMode.sessionToken || clientSdk.sessionToken || client.sessionToken || "",
    avatarId: payload?.avatarId || sdkMode.avatarId || clientSdk.avatarId || clientSdk.characterId || client.avatarId || client.characterId || "",
    environment: sdkMode.environment || payload?.environment || clientSdk.environment || client.environment || "production",
    sampleRate: Number(audioFormat.sampleRate || 16000),
    channelCount: Number(audioFormat.channelCount || 1),
  };
}

function avatarSdkMissingMetadataReason(payload = activeAvatarSession) {
  const metadata = avatarSdkClientMetadata(payload);
  if (!metadata.appId) {
    return "sdk_app_id_missing";
  }
  if (!metadata.sessionToken) {
    return "sdk_session_token_missing";
  }
  if (!metadata.avatarId) {
    return "sdk_avatar_id_missing";
  }
  return "";
}

async function importSpatialRealAvatarKit() {
  try {
    return await import("@spatialwalk/avatarkit");
  } catch (error) {
    throw new Error(`sdk_import_failed:${errorMessage(error)}`);
  }
}

function setAvatarSdkPlaybackVolume(controller, volume = AVATAR_SDK_SYNCED_PLAYBACK_VOLUME) {
  if (!controller) {
    throw new Error("sdk_controller_unavailable");
  }
  const safeVolume = Math.max(0, Math.min(1, Number(volume)));
  if (typeof controller.setVolume === "function") {
    controller.setVolume(safeVolume);
    return "setVolume";
  }
  if ("volume" in controller) {
    controller.volume = safeVolume;
    return "volume";
  }
  throw new Error("sdk_volume_unavailable");
}

function resetAvatarSdkPcmStats() {
  avatarSdkPcmStats = { chunks: 0, bytes: 0, sends: 0, nullSends: 0, silentDrops: 0, rmsMax: 0, startedAt: Date.now(), lastChunkAt: 0, lastSpeechAt: 0, responseDoneAt: 0, speechStarted: false };
}

function notifyAvatarSdkConnected() {
  const waiters = avatarSdkConnectionWaiters;
  avatarSdkConnectionWaiters = [];
  waiters.forEach((resolve) => resolve(true));
}

function waitForAvatarSdkConnected(timeoutMs = AVATAR_SDK_CONNECTED_WAIT_MS) {
  if (avatarSdkConnectionState === "connected") {
    return Promise.resolve(true);
  }
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => {
      avatarSdkConnectionWaiters = avatarSdkConnectionWaiters.filter((waiter) => waiter !== finish);
      resolve(false);
    }, timeoutMs);
    const finish = (connected) => {
      window.clearTimeout(timer);
      resolve(Boolean(connected));
    };
    avatarSdkConnectionWaiters.push(finish);
  });
}

function clearAvatarPcmBridgeIdleTimer() {
  if (avatarPcmBridgeIdleTimer) {
    window.clearTimeout(avatarPcmBridgeIdleTimer);
    avatarPcmBridgeIdleTimer = null;
  }
}

function clearAvatarPcmBridgeEndTimer() {
  if (avatarPcmBridgeEndTimer) {
    window.clearTimeout(avatarPcmBridgeEndTimer);
    avatarPcmBridgeEndTimer = null;
  }
}

function appendAvatarSdkPcmSummary(reason = "summary") {
  if (!avatarSdkPcmStats.startedAt) {
    return;
  }
  const now = Date.now();
  const elapsedMs = now - avatarSdkPcmStats.startedAt;
  const lastChunkAgeMs = avatarSdkPcmStats.lastChunkAt ? now - avatarSdkPcmStats.lastChunkAt : -1;
  const lastSpeechAgeMs = avatarSdkPcmStats.lastSpeechAt ? now - avatarSdkPcmStats.lastSpeechAt : -1;
  appendLog(`avatar SDK PCM ${reason}: chunks=${avatarSdkPcmStats.chunks}; bytes=${avatarSdkPcmStats.bytes}; sends=${avatarSdkPcmStats.sends}; nullSends=${avatarSdkPcmStats.nullSends}; silentDrops=${avatarSdkPcmStats.silentDrops}; speechStarted=${Boolean(avatarSdkPcmStats.speechStarted)}; rmsMax=${avatarSdkPcmStats.rmsMax.toFixed(4)}; connection=${avatarSdkConnectionState}; elapsedMs=${elapsedMs}; lastChunkAgeMs=${lastChunkAgeMs}; lastSpeechAgeMs=${lastSpeechAgeMs}; media hidden`);
}

function markAvatarSdkPcmSpeech(rms, source = "stream") {
  avatarSdkPcmStats.lastSpeechAt = Date.now();
  if (!avatarSdkPcmStats.speechStarted) {
    avatarSdkPcmStats.speechStarted = true;
    appendLog(`avatar SDK PCM speech detected${source ? ` on ${source}` : ""}: rms=${rms.toFixed(4)}; threshold=${AVATAR_PCM_SPEECH_RMS_THRESHOLD}; connection=${avatarSdkConnectionState}; media hidden`);
  }
}

function pcm16Rms(pcmBuffer) {
  if (!pcmBuffer || pcmBuffer.byteLength < 2) {
    return 0;
  }
  const view = new DataView(pcmBuffer);
  let total = 0;
  const samples = Math.floor(pcmBuffer.byteLength / 2);
  for (let offset = 0; offset + 1 < pcmBuffer.byteLength; offset += 2) {
    const value = view.getInt16(offset, true) / 32768;
    total += value * value;
  }
  return samples ? Math.sqrt(total / samples) : 0;
}

function shouldDropAvatarSdkSilence(pcmBuffer) {
  const rms = pcm16Rms(pcmBuffer);
  avatarSdkPcmStats.rmsMax = Math.max(avatarSdkPcmStats.rmsMax, rms);
  if (rms >= AVATAR_PCM_SPEECH_RMS_THRESHOLD) {
    markAvatarSdkPcmSpeech(rms, "stream");
    return false;
  }
  if (avatarSdkPcmStats.speechStarted) {
    return false;
  }
  avatarSdkPcmStats.silentDrops += 1;
  if (avatarSdkPcmStats.silentDrops === 1 || avatarSdkPcmStats.silentDrops % 25 === 0) {
    appendLog(`avatar SDK PCM silence dropped before speech: drops=${avatarSdkPcmStats.silentDrops}; rms=${rms.toFixed(4)}; threshold=${AVATAR_PCM_SPEECH_RMS_THRESHOLD}; connection=${avatarSdkConnectionState}; media hidden`);
  }
  return true;
}

function sendAvatarSdkPcmChunk(controller, pcmBuffer, isLast = false) {
  if (!controller || typeof controller.send !== "function") {
    throw new Error("sdk_controller_send_unavailable");
  }
  const bytes = pcmBuffer?.byteLength || 0;
  const rms = pcm16Rms(pcmBuffer);
  if (avatarSdkPcmStats.chunks === 0) {
    clearAvatarPcmBridgeIdleTimer();
  }
  avatarSdkPcmStats.chunks += 1;
  avatarSdkPcmStats.bytes += bytes;
  avatarSdkPcmStats.lastChunkAt = Date.now();
  avatarSdkPcmStats.rmsMax = Math.max(avatarSdkPcmStats.rmsMax, rms);
  if (rms >= AVATAR_PCM_SPEECH_RMS_THRESHOLD) {
    markAvatarSdkPcmSpeech(rms, isLast ? "final chunk" : "send");
  }
  const conversationId = controller.send(pcmBuffer || new ArrayBuffer(0), isLast);
  if (conversationId) {
    avatarSdkPcmStats.sends += 1;
  } else {
    avatarSdkPcmStats.nullSends += 1;
  }
  if (avatarSdkPcmStats.chunks === 1 || isLast || avatarSdkPcmStats.chunks % 25 === 0) {
    appendLog(`avatar SDK PCM chunk ${avatarSdkPcmStats.chunks}: bytes=${bytes}; rms=${rms.toFixed(4)}; final=${Boolean(isLast)}; accepted=${Boolean(conversationId)}; connection=${avatarSdkConnectionState}; media hidden`);
  }
  return conversationId;
}

function createAvatarPcmSourceStream(track) {
  if (avatarSdkSyncedPlaybackActive) {
    return { stream: new MediaStream([track]), source: "realtime-remote-track-pre-output" };
  }
  if (interviewerAudio?.srcObject && (typeof interviewerAudio.captureStream === "function" || typeof interviewerAudio.mozCaptureStream === "function")) {
    try {
      const capture = interviewerAudio.captureStream || interviewerAudio.mozCaptureStream;
      const capturedStream = capture.call(interviewerAudio);
      const capturedTrack = capturedStream?.getAudioTracks?.()[0] || null;
      if (capturedTrack) {
        return { stream: new MediaStream([capturedTrack]), source: "interviewer-audio-element-capture" };
      }
    } catch (error) {
      appendLog(`avatar SDK PCM source element capture unavailable: ${errorMessage(error)}; falling back to Realtime track; media hidden`);
    }
  }
  return { stream: new MediaStream([track]), source: "realtime-remote-track" };
}

function createAvatarPcmBridge(track, controller, sampleRate = 16000) {
  if (!track || track.kind !== "audio") {
    throw new Error("realtime_audio_track_unavailable");
  }
  if (!controller || typeof controller.send !== "function") {
    throw new Error("sdk_controller_send_unavailable");
  }
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) {
    throw new Error("audio_context_unavailable");
  }
  const context = new AudioContextClass();
  appendLog("avatar SDK PCM bridge created with ScriptProcessorNode diagnostic path; browser deprecation warning is expected and not treated as lip-sync failure; media hidden");
  const sourceSelection = createAvatarPcmSourceStream(track);
  const source = context.createMediaStreamSource(sourceSelection.stream);
  appendLog(`avatar SDK PCM source selected: ${sourceSelection.source}; response feed gated; media hidden`);
  const processor = context.createScriptProcessor(4096, 1, 1);
  let carry = new Float32Array(0);
  let ended = false;

  const downsampleToPcm16 = (input, inputSampleRate, outputSampleRate) => {
    if (!input.length || !inputSampleRate || !outputSampleRate) {
      return null;
    }
    const ratio = inputSampleRate / outputSampleRate;
    const outputLength = Math.floor(input.length / ratio);
    if (outputLength <= 0) {
      return null;
    }
    const buffer = new ArrayBuffer(outputLength * 2);
    const view = new DataView(buffer);
    for (let index = 0; index < outputLength; index += 1) {
      const start = Math.floor(index * ratio);
      const end = Math.min(input.length, Math.floor((index + 1) * ratio));
      let total = 0;
      let count = 0;
      for (let cursor = start; cursor < end; cursor += 1) {
        total += input[cursor];
        count += 1;
      }
      const sample = Math.max(-1, Math.min(1, count ? total / count : input[start] || 0));
      view.setInt16(index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    }
    return buffer;
  };

  processor.onaudioprocess = (event) => {
    if (ended || !avatarSdkResponseFeedActive) {
      return;
    }
    const input = event.inputBuffer.getChannelData(0);
    const combined = new Float32Array(carry.length + input.length);
    combined.set(carry);
    combined.set(input, carry.length);
    const minFrameCount = Math.max(1, Math.floor(context.sampleRate / 20));
    if (combined.length < minFrameCount) {
      carry = combined;
      return;
    }
    const usableLength = Math.floor(combined.length / minFrameCount) * minFrameCount;
    const usable = combined.slice(0, usableLength);
    carry = combined.slice(usableLength);
    const pcm = downsampleToPcm16(usable, context.sampleRate, sampleRate);
    if (!pcm || pcm.byteLength % 2 !== 0) {
      return;
    }
    if (avatarSdkConnectionState !== "connected") {
      avatarSdkPcmStats.silentDrops += 1;
      if (avatarSdkPcmStats.silentDrops === 1 || avatarSdkPcmStats.silentDrops % 25 === 0) {
        appendLog(`avatar SDK PCM held until connected: drops=${avatarSdkPcmStats.silentDrops}; connection=${avatarSdkConnectionState}; media hidden`);
      }
      return;
    }
    if (shouldDropAvatarSdkSilence(pcm)) {
      return;
    }
    try {
      sendAvatarSdkPcmChunk(controller, pcm, false);
    } catch (error) {
      renderAvatarSdkDegraded(`sdk_pcm_send_failed:${errorMessage(error)}`);
    }
  };

  source.connect(processor);
  processor.connect(context.destination);

  return {
    async start() {
      if (context.state === "suspended") {
        await context.resume();
      }
    },
    async end() {
      if (ended) {
        return;
      }
      ended = true;
      try {
        const finalChunk = carry.length ? downsampleToPcm16(carry, context.sampleRate, sampleRate) : new ArrayBuffer(0);
        const finalRms = pcm16Rms(finalChunk || new ArrayBuffer(0));
        if (avatarSdkPcmStats.speechStarted || finalRms >= AVATAR_PCM_SPEECH_RMS_THRESHOLD) {
          if (finalRms >= AVATAR_PCM_SPEECH_RMS_THRESHOLD) {
            markAvatarSdkPcmSpeech(finalRms, "final chunk");
          }
          sendAvatarSdkPcmChunk(controller, finalChunk || new ArrayBuffer(0), true);
        } else {
          avatarSdkPcmStats.silentDrops += 1;
          appendLog(`avatar SDK PCM final silence dropped: rms=${finalRms.toFixed(4)}; threshold=${AVATAR_PCM_SPEECH_RMS_THRESHOLD}; no avatar end marker needed before speech; media hidden`);
        }
        appendAvatarSdkPcmSummary("end");
      } finally {
        carry = new Float32Array(0);
      }
    },
    close() {
      ended = true;
      processor.disconnect();
      source.disconnect();
      context.close().catch(() => {});
    },
  };
}

async function startAvatarPcmBridgeIfReady(track = realtimeRemoteAudioTrack) {
  if (!activeAvatarSdkRuntime?.controller || !track || avatarPcmBridge) {
    return;
  }
  try {
    resetAvatarSdkPcmStats();
    avatarPcmBridge = createAvatarPcmBridge(track, activeAvatarSdkRuntime.controller, activeAvatarSdkRuntime.sampleRate || 16000);
    await avatarPcmBridge.start();
    avatarSdkModeState = { ...avatarSdkModeState, audioBridge: "pcm16_active" };
    appendLog(`avatar SDK PCM16 bridge active; connection=${avatarSdkConnectionState}; trackReadyState=${track.readyState || "unknown"}; trackMuted=${Boolean(track.muted)}; trackEnabled=${Boolean(track.enabled)}; audiblePath=${avatarSdkSyncedPlaybackActive ? "spatialreal-sdk-synced-playback" : "realtime-direct-fallback"}; media hidden`);
    clearAvatarPcmBridgeIdleTimer();
    avatarPcmBridgeIdleTimer = window.setTimeout(() => {
      if (avatarPcmBridge && avatarSdkResponseFeedActive && avatarSdkPcmStats.startedAt && avatarSdkPcmStats.chunks === 0) {
        appendLog(`avatar SDK PCM bridge idle during response feed: no audio frames after 2000ms; connection=${avatarSdkConnectionState}; trackReadyState=${track.readyState || "unknown"}; trackMuted=${Boolean(track.muted)}; trackEnabled=${Boolean(track.enabled)}; ScriptProcessorNode deprecation warning is not the failure; media hidden`);
      }
    }, 2000);
  } catch (error) {
    renderAvatarSdkDegraded(`sdk_pcm_bridge_failed:${errorMessage(error)}`);
  }
}

async function endAvatarPcmBridgeRound() {
  if (!avatarPcmBridge) {
    return;
  }
  try {
    const bridge = avatarPcmBridge;
    avatarPcmBridge = null;
    clearAvatarPcmBridgeIdleTimer();
    await bridge.end();
    bridge.close();
    avatarSdkResponseFeedActive = false;
    appendLog("avatar SDK PCM16 end marker sent; Realtime/MMM ownership unchanged");
  } catch (error) {
    renderAvatarSdkDegraded(`sdk_pcm_end_failed:${errorMessage(error)}`);
  }
}

function avatarSdkBeginResponseFeed(trigger = "audio.delta") {
  const safeTrigger = String(trigger || "audio.delta").replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 80);
  if (!activeAvatarSdkRuntime?.controller) {
    appendLog(`avatar SDK response feed skipped: SDK runtime not ready during ${safeTrigger}; first response may not drive avatar; media hidden`);
    return;
  }
  const wasActive = avatarSdkResponseFeedActive;
  avatarSdkResponseFeedActive = true;
  clearAvatarPcmBridgeEndTimer();
  if (!wasActive) {
    appendLog(`avatar SDK response feed active from ${safeTrigger}; connection=${avatarSdkConnectionState}; media hidden`);
  }
  startAvatarPcmBridgeIfReady(realtimeRemoteAudioTrack).catch((error) => {
    renderAvatarSdkDegraded(`sdk_pcm_bridge_failed:${errorMessage(error)}`);
  });
}

function getAvatarSdkPcmTailDrainDecision(drainStartedAt) {
  const now = Date.now();
  const elapsedMs = now - drainStartedAt;
  const sinceSpeechMs = avatarSdkPcmStats.lastSpeechAt ? now - avatarSdkPcmStats.lastSpeechAt : Number.POSITIVE_INFINITY;
  const sinceChunkMs = avatarSdkPcmStats.lastChunkAt ? now - avatarSdkPcmStats.lastChunkAt : Number.POSITIVE_INFINITY;
  if (!avatarPcmBridge) {
    return { shouldContinue: false, reason: "no_bridge", elapsedMs, sinceSpeechMs, sinceChunkMs };
  }
  if (avatarSdkPcmStats.speechStarted && elapsedMs >= AVATAR_PCM_MAX_DRAIN_MS) {
    return { shouldContinue: false, reason: "max_drain", elapsedMs, sinceSpeechMs, sinceChunkMs };
  }
  if (!avatarSdkPcmStats.speechStarted && elapsedMs >= AVATAR_PCM_NO_SPEECH_DRAIN_MS) {
    return { shouldContinue: false, reason: "no_speech_drain_timeout", elapsedMs, sinceSpeechMs, sinceChunkMs };
  }
  if (elapsedMs < AVATAR_PCM_END_GRACE_MS) {
    return { shouldContinue: true, reason: "min_grace", elapsedMs, sinceSpeechMs, sinceChunkMs };
  }
  if (!avatarSdkPcmStats.speechStarted) {
    return { shouldContinue: true, reason: "waiting_for_speech", elapsedMs, sinceSpeechMs, sinceChunkMs };
  }
  if (sinceSpeechMs < AVATAR_PCM_TAIL_SILENCE_MS) {
    return { shouldContinue: true, reason: "recent_speech", elapsedMs, sinceSpeechMs, sinceChunkMs };
  }
  return { shouldContinue: false, reason: "tail_silence", elapsedMs, sinceSpeechMs, sinceChunkMs };
}

function scheduleAvatarSdkPcmTailDrain(safeResponseId, drainStartedAt) {
  clearAvatarPcmBridgeEndTimer();
  avatarPcmBridgeEndTimer = window.setTimeout(() => {
    avatarPcmBridgeEndTimer = null;
    const decision = getAvatarSdkPcmTailDrainDecision(drainStartedAt);
    const sinceSpeechLog = Number.isFinite(decision.sinceSpeechMs) ? decision.sinceSpeechMs : -1;
    const sinceChunkLog = Number.isFinite(decision.sinceChunkMs) ? decision.sinceChunkMs : -1;
    if (decision.shouldContinue) {
      if (decision.reason !== "min_grace" || Math.abs(decision.elapsedMs % 1000) < AVATAR_PCM_TAIL_POLL_MS) {
        appendLog(`avatar SDK PCM tail drain continuing: response=${safeResponseId}; reason=${decision.reason}; elapsedMs=${decision.elapsedMs}; sinceSpeechMs=${sinceSpeechLog}; sinceChunkMs=${sinceChunkLog}; chunks=${avatarSdkPcmStats.chunks}; media hidden`);
      }
      scheduleAvatarSdkPcmTailDrain(safeResponseId, drainStartedAt);
      return;
    }
    appendLog(`avatar SDK PCM tail drain ending: response=${safeResponseId}; reason=${decision.reason}; elapsedMs=${decision.elapsedMs}; sinceSpeechMs=${sinceSpeechLog}; sinceChunkMs=${sinceChunkLog}; chunks=${avatarSdkPcmStats.chunks}; media hidden`);
    endAvatarPcmBridgeRound()
      .then(() => {
        appendLog(`avatar SDK response feed ended: ${safeResponseId}; Realtime question boundary already released; tokens hidden`);
      })
      .catch((error) => {
        appendLog(`avatar SDK response feed end skipped: ${errorMessage(error)}; Realtime question boundary already released`);
      });
  }, AVATAR_PCM_TAIL_POLL_MS);
}

function avatarSdkEndResponseFeed(responseId = "") {
  if (!avatarSdkResponseFeedActive && !avatarPcmBridge) {
    appendLog("avatar SDK response feed end skipped: no active PCM feed; media hidden");
    return;
  }
  if (!activeAvatarSdkRuntime?.controller && !avatarPcmBridge) {
    avatarSdkResponseFeedActive = false;
    return;
  }
  const safeResponseId = String(responseId || "response").replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 80);
  const drainStartedAt = Date.now();
  avatarSdkPcmStats.responseDoneAt = drainStartedAt;
  appendLog(`avatar SDK PCM tail drain started: response=${safeResponseId}; minGraceMs=${AVATAR_PCM_END_GRACE_MS}; tailSilenceMs=${AVATAR_PCM_TAIL_SILENCE_MS}; maxDrainMs=${AVATAR_PCM_MAX_DRAIN_MS}; noSpeechDrainMs=${AVATAR_PCM_NO_SPEECH_DRAIN_MS}; Realtime question boundary already released`);
  scheduleAvatarSdkPcmTailDrain(safeResponseId, drainStartedAt);
}

function renderAvatarSdkModeStatus(payload = activeAvatarSession) {
  const state = normalizeAvatarSdkModeState(payload);
  avatarSdkModeState = { ...avatarSdkModeState, ...state };
  const safeMode = String(state.mode).replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 80);
  const safeOutcome = String(state.outcome).replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 80);
  const safeAudioFeed = String(state.audioFeed).replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 80);
  appendLog(`${LIVEKIT_FREE_REALTIME_MAIN_PATH_LABEL}; ${AVATAR_DEFERRED_LABEL}; ${SPATIALREAL_SDK_MODE_LABEL} ${safeMode}:${safeOutcome}; ${state.transport}; ${safeAudioFeed}; tokens hidden; media hidden`);
}

function captureRealtimeRemoteAudioTrack(track) {
  if (!track || track.kind !== "audio") {
    return;
  }
  realtimeRemoteAudioTrack = track;
  if (activeRealtimeSession) {
    activeRealtimeSession.remoteAudioTrack = track;
  }
  renderAvatarSdkModeStatus();
  if (avatarSdkResponseFeedActive) {
    startAvatarPcmBridgeIfReady(track);
  }
  appendLog("Realtime remote audio track observed for interviewer playback; avatar SDK PCM16 adapter waits for response feed; media hidden");
  if (typeof track.addEventListener === "function") {
    track.addEventListener("mute", () => {
      appendLog("Realtime remote audio track muted; avatar SDK PCM bridge may idle until audio resumes; media hidden");
    });
    track.addEventListener("unmute", () => {
      appendLog("Realtime remote audio track unmuted; avatar SDK PCM bridge should receive frames on interviewer audio; media hidden");
    });
    track.addEventListener("ended", () => {
      if (realtimeRemoteAudioTrack === track) {
        realtimeRemoteAudioTrack = null;
      }
      avatarPcmBridge?.close();
      avatarPcmBridge = null;
      avatarSdkResponseFeedActive = false;
      clearAvatarPcmBridgeIdleTimer();
      clearAvatarPcmBridgeEndTimer();
      appendLog("Realtime remote audio track ended; avatar SDK PCM16 bridge closed; media hidden");
    }, { once: true });
  }
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

function safeRealtimeSessionUpdatePayload(brokerSession) {
  const update = brokerSession?.webrtc?.postConnectSessionUpdate;
  if (!update || update.type !== "session.update" || typeof update.session !== "object") {
    return null;
  }
  return update;
}

function sendRealtimePostConnectSessionUpdate(brokerSession) {
  const update = safeRealtimeSessionUpdatePayload(brokerSession);
  const channel = activeRealtimeSession?.dataChannel;
  if (!update || !channel || channel.readyState !== "open") {
    appendLog("Realtime post-connect STT/VAD session.update skipped; safe config unavailable or data channel closed");
    return;
  }
  channel.send(JSON.stringify(update));
  appendLog("Realtime STT/VAD session.update sent after WebRTC attach; auto response remains disabled; secrets hidden");
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

function relayApiApprovedRealtimeCommand(payload) {
  const command = payload?.sideband?.command;
  const channel = activeRealtimeSession?.dataChannel;
  if (!command || command.type !== "response.create") {
    throw new Error("API-approved Realtime response command unavailable");
  }
  if (!channel || channel.readyState !== "open") {
    throw new Error("Realtime data channel is not open for API-approved response command relay");
  }
  channel.send(JSON.stringify(command));
  appendLog("API-approved Realtime response.create relayed over browser transport; browser did not author prompt; internal terms hidden");
}

async function requestApiRealtimeResponse(reason = "manual", turnIndex = currentTurnIndex) {
  realtimeFirstAudioMarked = false;
  realtimeResponseInFlight = true;
  realtimeInterviewerQuestionTranscript = "";
  const response = await fetch(realtimeResponseEndpoint(turnIndex), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      reason,
      sessionId: analysisSessionId(),
      response: {
        outputModalities: ["audio"],
        instructions: REALTIME_INTERVIEWER_RESPONSE_INSTRUCTIONS,
      },
    }),
  });
  const payload = await response.json().catch(() => ({}));
  renderMmmDebug("/realtime/response", payload);
  if (!response.ok) {
    throw new Error(payload.message || payload.error || `request failed: HTTP ${response.status}`);
  }
  relayApiApprovedRealtimeCommand(payload);
  await postRealtimeTurnEvent("realtime.response.create", { reason, owner: "api", transport: "browser-data-channel-relay" }, turnIndex);
  appendLog(`Realtime response requested through API control plane: ${reason}; response.create command was API-approved`);
  return payload;
}

function extractRealtimeInputTranscript(event) {
  if (typeof event?.transcript === "string") {
    return event.transcript.trim();
  }
  return "";
}

function handleRealtimeServerEvent(event) {
  const type = String(event?.type || "unknown");
  if (type === "response.created") {
    activeRealtimeResponseId = event.response?.id || event.response_id || event.id || "";
    renderAvatarSdkModeStatus();
    appendLog("avatar SDK response created; PCM feed opens when SDK is ready and silence is gated until speech; media hidden");
    avatarSdkBeginResponseFeed(type);
    return;
  }
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
      appendLog("Realtime transcript completion kept on API sideband only; no browser conversation injection");
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
    avatarSdkBeginResponseFeed(type);
    return;
  }
  if (type === "response.done") {
    const responseId = event.response?.id || event.response_id || activeRealtimeResponseId;
    renderRealtimeQuestionDone(event);
    realtimeResponseInFlight = false;
    markInterviewerQuestionEnded({ provider: "openai-realtime", turnIndex: currentTurnIndex });
    activeRealtimeResponseId = "";
    avatarSdkEndResponseFeed(responseId);
  }
}

function bindRealtimeDataChannel(channel) {
  channel.addEventListener("open", () => {
    appendLog("Realtime data channel open; browser-authored response.create disabled; API owns next-question command creation");
  });
  channel.addEventListener("message", (event) => {
    try {
      handleRealtimeServerEvent(JSON.parse(event.data));
    } catch (error) {
      appendLog(`Realtime event ignored: ${errorMessage(error)}`);
    }
  });
  channel.addEventListener("close", () => {
    appendLog("Realtime data channel closed");
  });
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
    renderMmmDebug("/mmm-ready", payload);
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
  await requestApiRealtimeResponse(reason, currentTurnIndex);
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
    if (!remoteStream.getTracks().includes(event.track)) {
      remoteStream.addTrack(event.track);
    }
    captureRealtimeRemoteAudioTrack(event.track);
    attachRealtimeRemoteAudio(remoteStream);
  });
  peerConnection.addEventListener("connectionstatechange", () => {
    if (["closed", "disconnected", "failed"].includes(peerConnection.connectionState)) {
      appendLog(`Realtime peer state ${peerConnection.connectionState}; avatar SDK Mode remains deferred`);
    }
  });
  const localStream = await ensureRealtimeAudioStream();
  localStream.getAudioTracks().forEach((track) => peerConnection.addTrack(track, localStream));
  // Keep the OpenAI Realtime offer to a single audio m-section.
  // Adding an extra recvonly audio transceiver makes /v1/realtime/calls reject
  // otherwise valid browser offers with a provider-side 400.
  activeRealtimeSession = { peerConnection, dataChannel, localStream, brokerSession, remoteAudioTrack: realtimeRemoteAudioTrack };
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
  appendLog("Realtime WebRTC connected through API-mediated call broker; OpenAI standard API key stays server-side");
  await waitForRealtimeDataChannelOpen(dataChannel);
  sendRealtimePostConnectSessionUpdate(brokerSession);
  nextQuestionRequested = false;
  appendLog("Realtime connected; first question waits for avatar session readiness check; media hidden");
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
  realtimeRemoteAudioTrack = null;
  activeRealtimeResponseId = "";
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
    syncMediaUi();
    await applyRealtimeMediaState();
    await syncCameraPreviewForCameraState("answer-end-camera-preserve");
    const transcriptReady = await waitForRealtimeTranscriptCompletion();
    if (!transcriptReady) {
      renderTranscriptStatus("Realtime 전사 결과가 없습니다. 마이크 입력/브라우저 권한/무음 상태를 확인한 뒤 다시 답변해 주세요.");
      setAnswerTurnAvailability(true, "candidate answer ended without transcript; next question blocked for retry");
      throw new Error("Realtime transcript unavailable; next question blocked");
    }
    await sendBoundedVisionEvent("answer_end", completedTurnIndex);
    await sendRealtimeProsodyEvent("answer_end", completedTurnIndex);
    await postRealtimeTurnEvent("turn.answer.end", {
      source: "browser-manual-button",
      transcriptAvailable: true,
      rawTranscriptIncluded: false,
      rawMediaIncluded: false,
    }, completedTurnIndex);
    lastAnswerTranscript = realtimeAnswerTranscript || "Realtime transcript unavailable.";
    realtimeAnswerTranscript = "";
    realtimeTranscriptCompleted = false;
    renderTranscriptStatus("답변 종료. full MMM 준비 신호를 기다리는 중입니다.");
    await waitForFullMmmReady(completedTurnIndex);
    requestCoachFeedback(completedTurnIndex);
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
    setAvatarPanelMessage("Optional avatar media egress completed outside the Realtime/MMM success path. OpenAI Realtime remains the interviewer audio owner; tokens hidden.");
    appendLog(`optional avatar egress sent; publisher ${avatarRtc.publisherId || "unknown"}; tokens hidden`);
    return;
  }
  if (status === "skipped") {
    setAvatarPanelMessage(`${AVATAR_DEFERRED_LABEL}: optional avatar egress skipped (${reason || "not_ready"}). ${LIVEKIT_FREE_REALTIME_MAIN_PATH_LABEL} continues.`);
    appendLog(`optional avatar egress skipped: ${reason || "unknown"}; tokens hidden`);
    return;
  }
  if (status === "failed") {
    setAvatarPanelMessage(`${AVATAR_DEFERRED_LABEL}: optional avatar egress failed (${reason || "provider_request_failed"}). Realtime interviewer audio continues.`);
    appendLog(`optional avatar egress failed: ${reason || "unknown"}; tokens hidden`);
  }
}

async function disconnectAvatarRtc() {
  avatarPcmBridge?.close();
  avatarPcmBridge = null;
  avatarSdkResponseFeedActive = false;
  avatarSdkConnectionWaiters.splice(0).forEach((resolve) => resolve(false));
  clearAvatarPcmBridgeIdleTimer();
  clearAvatarPcmBridgeEndTimer();
  setRealtimeDirectAudioOutputMutedForAvatar(false, "avatar-disconnect");
  activeAvatarSdkRuntime?.avatarView?.dispose?.();
  activeAvatarSdkRuntime?.sdk?.AvatarSDK?.cleanup?.();
  activeAvatarSdkRuntime = null;
  avatarSdkConnectionState = "disconnected";
  avatarSdkInitializePromise = null;
  avatarSdkModeState = { ...avatarSdkModeState, initialized: false, reason: "disconnected", audioFeed: SPATIALREAL_SDK_AUDIO_FEED_FORMAT };
  avatarRenderTarget?.classList.remove("is-rtc-active", "is-sdk-active");
  appendLog(`${AVATAR_DEFERRED_LABEL}: disconnected; ${LIVEKIT_FREE_REALTIME_MAIN_PATH_LABEL} unaffected`);
}

function renderAvatarSdkDegraded(reason) {
  setRealtimeDirectAudioOutputMutedForAvatar(false, "avatar-degraded");
  avatarSdkModeState = { initialized: false, outcome: SPATIALREAL_SDK_DEFERRED_OUTCOME, reason: String(reason || "sdk_mode_deferred"), audioFeed: SPATIALREAL_SDK_AUDIO_FEED_FORMAT };
  setAvatarRtcState("disabled", AVATAR_DEFERRED_LABEL);
  setAvatarPanelMessage(`${AVATAR_DEFERRED_LABEL}: ${reason}. OpenAI Realtime owns STT/VAD/interviewer audio. ${SPATIALREAL_SDK_MODE_LABEL} remains ${SPATIALREAL_SDK_DEFERRED_OUTCOME}; no production lip-sync claim.`);
  appendLog(`${AVATAR_DEFERRED_LABEL}: ${reason}; ${LIVEKIT_FREE_REALTIME_MAIN_PATH_LABEL}; tokens hidden; media hidden`);
}

async function initializeSpatialRealSdkAvatar(payload) {
  if (!payload?.ready || payload?.provider !== "spatialreal") {
    renderAvatarSdkDegraded("spatialreal_session_not_ready");
    return;
  }
  if (!isSpatialRealSdkModeEnabled(payload)) {
    renderAvatarSdkDegraded("sdk_mode_deferred");
    return;
  }
  const missingReason = avatarSdkMissingMetadataReason(payload);
  if (missingReason) {
    renderAvatarSdkDegraded(missingReason);
    appendLog(`avatar SDK metadata missing: ${missingReason}; coordinate API metadata with worker-1`);
    return;
  }
  if (avatarSdkInitializePromise) {
    await avatarSdkInitializePromise;
    return;
  }
  avatarSdkInitializePromise = (async () => {
    const metadata = avatarSdkClientMetadata(payload);
    const sdk = await importSpatialRealAvatarKit();
    const { AvatarSDK, AvatarManager, DrivingServiceMode } = sdk;
    if (!AvatarSDK || !AvatarManager?.shared || !sdk.AvatarView) {
      throw new Error("sdk_exports_unavailable");
    }
    await AvatarSDK.initialize(metadata.appId, {
      environment: metadata.environment,
      drivingServiceMode: DrivingServiceMode?.sdk || "sdk",
      logLevel: "error",
      audioFormat: { channelCount: metadata.channelCount || 1, sampleRate: metadata.sampleRate || 16000 },
    });
    AvatarSDK.setSessionToken(metadata.sessionToken);
    const avatar = await AvatarManager.shared.load(metadata.avatarId);
    if (!avatarRenderTarget) {
      throw new Error("avatar_render_target_missing");
    }
    avatarRenderTarget.replaceChildren();
    const avatarView = new sdk.AvatarView(avatar, avatarRenderTarget);
    const controller = avatarView.controller;
    controller.onConnectionState = (state) => {
      avatarSdkConnectionState = String(state || "unknown");
      appendLog(`avatar SDK connection state: ${avatarSdkConnectionState}; tokens hidden`);
      if (avatarSdkConnectionState === "connected") {
        notifyAvatarSdkConnected();
      }
    };
    controller.onConversationState = (state) => {
      appendLog(`avatar SDK conversation state: ${String(state || "unknown")}; media hidden`);
    };
    controller.onError = (error) => {
      appendLog(`avatar SDK error: ${errorMessage(error)}; tokens hidden`);
    };
    const playbackMethod = setAvatarSdkPlaybackVolume(controller, AVATAR_SDK_SYNCED_PLAYBACK_VOLUME);
    await controller.initializeAudioContext();
    avatarSdkConnectionState = "connecting";
    await controller.start();
    setAvatarSdkPlaybackVolume(controller, AVATAR_SDK_SYNCED_PLAYBACK_VOLUME);
    setRealtimeDirectAudioOutputMutedForAvatar(true, "avatar-sdk-synced-playback");
    activeAvatarSdkRuntime = { sdk, avatarView, controller, sampleRate: metadata.sampleRate || 16000, playbackMethod };
    avatarSdkModeState = { ...normalizeAvatarSdkModeState(payload), initialized: true, reason: "sdk_mode_ready_synced_playback", playbackMethod };
    avatarRenderTarget?.classList.add("is-sdk-active");
    setAvatarRtcState("speaking", "Avatar SDK synced playback active");
    setAvatarPanelMessage(`${SPATIALREAL_SDK_MODE_LABEL} active with synced ${SPATIALREAL_SDK_AUDIO_FEED_FORMAT} playback. OpenAI Realtime still generates the interviewer audio; SpatialReal SDK owns audible playback for lip-sync.`);
    appendLog(`avatar SDK initialized; synced playback via ${playbackMethod}; volume=${AVATAR_SDK_SYNCED_PLAYBACK_VOLUME}; Realtime direct audio muted for lip-sync; session token hidden; ${LIVEKIT_FREE_REALTIME_MAIN_PATH_LABEL}`);
    if (avatarSdkResponseFeedActive) {
      await startAvatarPcmBridgeIfReady(realtimeRemoteAudioTrack);
    } else {
      appendLog("avatar SDK PCM bridge armed; waiting for Realtime response feed before sending audio; media hidden");
    }
  })().catch((error) => {
    avatarSdkInitializePromise = null;
    renderAvatarSdkDegraded(`sdk_init_failed:${errorMessage(error)}`);
  });
  await avatarSdkInitializePromise;
}

function renderAvatarState(payload) {
  activeAvatarSession = payload || null;
  const sdkModeStateForRender = payload?.ready ? normalizeAvatarSdkModeState(payload) : null;
  const readyForSdkInit = payload?.ready && sdkModeStateForRender?.metadataAccepted;
  const state = payload?.error ? "error" : readyForSdkInit ? "pending" : payload?.ready ? "disabled" : payload?.status === "disabled" ? "disabled" : "pending";
  const label = payload?.error ? "Avatar error" : readyForSdkInit ? "Avatar SDK 준비중" : payload?.ready ? AVATAR_DEFERRED_LABEL : avatarStatusLabel(payload);
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
      const sdkModeState = normalizeAvatarSdkModeState(payload);
      const sdkStatus = sdkModeState.metadataAccepted
        ? `${SPATIALREAL_SDK_MODE_LABEL} metadata accepted for ${sdkModeState.transport}; ${sdkModeState.outcome}`
        : `${SPATIALREAL_SDK_MODE_LABEL} ${SPATIALREAL_SDK_DEFERRED_OUTCOME} (${sdkModeState.reason || "feature flag off"})`;
      avatarPanelBody.textContent = sdkModeState.metadataAccepted
        ? `SpatialReal session metadata accepted. Initializing avatar SDK; session token is not shown. Audio feed ${sdkModeState.audioFeed}. ${sdkStatus}. ${LIVEKIT_FREE_REALTIME_MAIN_PATH_LABEL} continues.`
        : `SpatialReal session metadata is ready, but avatar rendering is disabled/deferred. Session token is not shown. Audio feed ${sdkModeState.audioFeed}. ${sdkStatus}. ${LIVEKIT_FREE_REALTIME_MAIN_PATH_LABEL} continues.`;
    } else if (payload?.reason) {
      avatarPanelBody.textContent = `${AVATAR_DEFERRED_LABEL}: ${payload.reason}. Provider keys stay server-side.`;
    } else if (payload?.error) {
      avatarPanelBody.textContent = `Avatar provider error: ${payload.message || payload.error}`;
    } else {
      avatarPanelBody.textContent = "Provider status pending; Realtime voice remains primary.";
    }
  }
  if (payload?.ready) {
    initializeSpatialRealSdkAvatar(payload).catch((error) => appendLog(`avatar SDK Mode init: ${errorMessage(error)}`));
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
    if (!response.ok && (payload.status === "disabled" || payload.status === "deferred" || payload.status === "blocked" || payload.reason === "realtime_only" || payload.error === "deprecated_ai_engine_removed")) {
      renderAvatarState({ ...payload, ready: false, status: payload.status || "deferred", provider: payload.provider || "api", reason: payload.reason || payload.error || "avatar_deferred" });
      appendLog(`avatar session deferred by API: ${payload.reason || payload.error || response.status}; no legacy ai-engine fallback; Realtime voice unaffected`);
      return payload;
    }
    if (!response.ok) {
      throw new Error(payload.message || payload.error || `avatar session failed: HTTP ${response.status}`);
    }
    renderAvatarState(payload);
    if (payload?.ready && avatarSdkInitializePromise) {
      appendLog("avatar session ready; waiting for SDK init before first Realtime question; tokens hidden");
      await avatarSdkInitializePromise;
      appendLog("avatar SDK init complete; waiting for SDK connection before first Realtime question; tokens hidden");
      const connected = await waitForAvatarSdkConnected();
      appendLog(`avatar SDK connection wait before first Realtime question: ${connected ? "connected" : "timeout"}; current=${avatarSdkConnectionState}; tokens hidden`);
    }
    appendLog(`avatar session state: ${payload.status || "unknown"}; provider ${payload.provider || "unknown"}; session token hidden; Realtime voice unaffected`);
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

function renderCoachFeedbackState(title, body, bullets = []) {
  if (coachFeedbackTitle) {
    coachFeedbackTitle.textContent = title;
  }
  if (coachFeedbackBody) {
    coachFeedbackBody.textContent = body;
  }
  if (coachFeedbackList) {
    coachFeedbackList.replaceChildren(...bullets.map((item) => {
      const li = document.createElement("li");
      li.textContent = String(item);
      return li;
    }));
  }
}

function renderCoachFeedback(payload) {
  const feedback = payload?.coachFeedback || {};
  if (!feedback.ready) {
    renderCoachFeedbackState("코치 피드백 대기", feedback.summary || "분석 결과를 기다리는 중입니다.", []);
    return;
  }
  const bullets = [
    feedback.answerEvaluation,
    feedback.multimodalEvaluation,
    ...(Array.isArray(feedback.bullets) ? feedback.bullets : []),
  ].filter(Boolean);
  renderCoachFeedbackState("코치 피드백", feedback.summary || "답변 피드백이 준비되었습니다.", bullets);
}

async function requestCoachFeedback(turnIndex) {
  renderCoachFeedbackState("코치 피드백 생성 중", "분석 결과를 코치 피드백으로 정리하고 있습니다.", []);
  try {
    const endpoint = `/api/interviews/${encodeURIComponent(activeInterviewId)}/turns/${turnIndex}/coach-feedback`;
    let lastPayload = null;
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const response = await fetch(endpoint, { headers: { Accept: "application/json" } });
      const payload = await response.json().catch(() => ({}));
      lastPayload = payload;
      if (!response.ok && response.status !== 202) {
        throw new Error(payload.message || payload.error || `coach feedback failed: HTTP ${response.status}`);
      }
      renderCoachFeedback(payload);
      if (response.ok && payload?.coachFeedback?.ready) {
        appendLog(`coach feedback ${payload.status || "received"} for turn ${turnIndex}; raw analysis hidden`);
        return payload;
      }
      appendLog(`coach feedback pending for turn ${turnIndex}: ${payload?.coachFeedback?.reason || payload?.status || "pending"}`);
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    renderCoachFeedback(lastPayload);
    return lastPayload;
  } catch (error) {
    const message = errorMessage(error);
    renderCoachFeedbackState("코치 피드백 사용 불가", "이번 턴의 코치 피드백을 가져오지 못했습니다. 다음 턴 진행은 계속됩니다.", []);
    appendLog(`coach feedback unavailable: ${message}`);
    return null;
  }
}

function isForbiddenDebugKey(key) {
  return /(?:raw|transcript|media|sdp|token|secret|client_secret|api[_-]?key|audio|video|frame)/i.test(String(key || ""));
}

function safeDebugScalar(value, maxLength = 220) {
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  if (typeof value === "string") {
    const redacted = redactSensitiveText(value).trim();
    return redacted.length > maxLength ? `${redacted.slice(0, maxLength)}…` : redacted;
  }
  return "";
}

function safeDebugObject(value, depth = 0) {
  if (depth > 2) {
    return "[redacted-depth]";
  }
  if (Array.isArray(value)) {
    return value.map((item) => safeDebugObject(item, depth + 1)).filter((item) => item !== "");
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value)
      .filter(([key]) => !isForbiddenDebugKey(key))
      .map(([key, item]) => [key, safeDebugObject(item, depth + 1)])
      .filter(([, item]) => item !== ""));
  }
  return safeDebugScalar(value);
}

function safeDebugJson(value) {
  const safe = safeDebugObject(value);
  if (safe === "" || (Array.isArray(safe) && safe.length === 0)) {
    return "";
  }
  if (safe && typeof safe === "object" && !Array.isArray(safe) && Object.keys(safe).length === 0) {
    return "";
  }
  const encoded = JSON.stringify(safe, null, 2);
  return encoded.length > 900 ? `${encoded.slice(0, 900)}…` : encoded;
}

function firstDebugValue(...values) {
  for (const value of values) {
    const rendered = safeDebugScalar(value);
    if (rendered) {
      return rendered;
    }
  }
  return "-";
}

function renderMmmDebug(source, payload = {}) {
  if (!mmmDebugSummary) {
    return;
  }
  const readiness = payload?.readiness && typeof payload.readiness === "object" ? payload.readiness : payload;
  const responseCreate = payload?.responseCreate && typeof payload.responseCreate === "object" ? payload.responseCreate : {};
  const analysisEngine = (payload?.analysisEngine && typeof payload.analysisEngine === "object")
    ? payload.analysisEngine
    : (readiness?.analysisEngine && typeof readiness.analysisEngine === "object" ? readiness.analysisEngine : {});
  const analysisResult = (payload?.analysisResult && typeof payload.analysisResult === "object")
    ? payload.analysisResult
    : (readiness?.analysisResult && typeof readiness.analysisResult === "object" ? readiness.analysisResult : {});
  const rows = [
    ["source", source],
    ["interviewId", payload?.interviewId || readiness?.interviewId],
    ["turnIndex", payload?.turnIndex || readiness?.turnIndex],
    ["analysisTurnIndex", payload?.analysisTurnIndex || readiness?.analysisTurnIndex],
    ["readiness.full_mmm_ready", readiness?.full_mmm_ready],
    ["readiness.state", readiness?.state || readiness?.status],
    ["readiness.reasonCodes", safeDebugJson(readiness?.reasonCodes || (readiness?.reason ? [readiness.reason] : []))],
    ["readiness.lanes", safeDebugJson(readiness?.lanes || {})],
    ["responseCreate.created", responseCreate.created],
    ["responseCreate.reason", responseCreate.reason || responseCreate.commandType],
    ["analysisEngine.endpoint", analysisEngine.endpoint],
    ["analysisEngine.status", analysisEngine.status],
    ["analysisEngine.error", analysisEngine.error],
    ["analysisResult.status", analysisResult.status],
    ["analysisResult.summary", analysisResult.publicSummary || analysisResult.summary],
    ["analysisResult.guidance", analysisResult.publicGuidance || analysisResult.guidance],
    ["analysisResult.coverage", safeDebugJson(analysisResult.coverage || {})],
    ["analysisResult.confidence", analysisResult.confidence],
    ["analysisResult.latency", analysisResult.latencyMs || analysisResult.latency],
  ];
  mmmDebugSummary.replaceChildren(...rows.map(([label, value]) => {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    detail.textContent = typeof value === "string" && value ? value : firstDebugValue(value);
    row.append(term, detail);
    return row;
  }));
}

function analysisSessionId() {
  return activeSession?.sessionId || activeInterviewId;
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
  if (question && isRealtimePrimary()) {
    postRealtimeTurnEvent("interviewer.question.completed", { question }, currentTurnIndex).catch(
      (err) => appendLog(`interviewer question store failed: ${errorMessage(err)}`)
    );
  }
  realtimeInterviewerQuestionTranscript = "";
}

function renderQuestionLoading() {
  if (currentQuestionTitle) {
    currentQuestionTitle.textContent = "질문 생성 중";
  }
  if (currentQuestionBody) {
    currentQuestionBody.textContent = isRealtimePrimary()
      ? "Realtime sideband가 full MMM 준비 이후 다음 질문을 발화합니다."
      : "Keyless scaffold InterviewController가 다음 질문 route smoke를 처리합니다.";
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
  const questionText = String(payload?.question || "").trim();
  if (!questionText) {
    appendLog("Realtime interviewer audio owns the question; legacy TTS fallback skipped");
  } else {
    appendLog("legacy TTS fallback removed; OpenAI Realtime audio remains the only live interviewer voice path");
  }
  if (interviewerMediaState) {
    interviewerMediaState.textContent = "질문 완료";
  }
}

async function requestNextQuestion(reason = "manual") {
  if (isRealtimePrimary() && activeRealtimeSession) {
    return requestRealtimeNextQuestion(reason);
  }
  nextQuestionRequested = false;
  renderInterviewQuestion(null);
  if (interviewerMediaState) {
    interviewerMediaState.textContent = "Realtime 대기";
  }
  setStatus("Realtime session required for interviewer audio; legacy question/TTS fallback removed", "error");
  appendLog(`legacy question fallback removed; blocked next-question request (${reason}); connect Realtime first`);
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
  const hasCameraPreview = Boolean(cameraEnabled && hasLiveCameraPreviewStream());
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

function hasLiveCameraPreviewStream() {
  return Boolean(localPreviewStream?.getVideoTracks?.().some((track) => track.readyState !== "ended"));
}

function attachCameraPreviewStream(stream = localPreviewStream) {
  if (!stream) {
    return;
  }
  if (localPreviewVideo && localPreviewVideo.srcObject !== stream) {
    localPreviewVideo.srcObject = stream;
  }
  if (candidateRoomVideo && candidateRoomVideo.srcObject !== stream) {
    candidateRoomVideo.srcObject = stream;
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

async function syncCameraPreviewForCameraState(reason = "camera-state") {
  if (!cameraEnabled) {
    const hadPreview = Boolean(localPreviewStream);
    stopPreviewStream();
    syncMediaUi();
    if (hadPreview) {
      appendLog(`camera preview stopped; reason=${reason}; Realtime audio track preserved`);
    }
    return null;
  }
  if (hasLiveCameraPreviewStream()) {
    attachCameraPreviewStream();
    syncMediaUi();
    appendLog(`camera preview reused; reason=${reason}; no video getUserMedia restart`);
    return localPreviewStream;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    cameraEnabled = false;
    syncMediaUi();
    throw new Error("browser media permissions are not available");
  }

  setStatus("requesting camera permission...", "connecting");
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: { width: { ideal: 1280 }, height: { ideal: 720 } },
  });
  localPreviewStream = stream;
  attachCameraPreviewStream(stream);
  syncMediaUi();
  setStatus("preview ready", activeRealtimeSession ? "connected" : "idle");
  appendLog(`camera preview started; reason=${reason}; answer ${micEnabled ? "recording" : "idle"}; tokens hidden`);
  return stream;
}

async function startPreview() {
  if (!cameraEnabled) {
    cameraEnabled = true;
  }
  await syncCameraPreviewForCameraState("preview-button");
}

async function applyMediaStateToRoom() {
  if (activeRealtimeSession) {
    await applyRealtimeMediaState();
    return;
  }
  appendLog(`legacy setMicrophoneEnabled/setCameraEnabled room media disabled; Realtime primary applies browser media only after connect`);
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
    renderTranscriptStatus("답변 중입니다. Realtime STT/VAD 이벤트와 bounded vision metadata를 API sideband로 전달합니다.");
    appendLog("candidate answer turn started; Realtime event boundary active; verbatim transcript hidden");
    return;
  }
  renderTranscriptStatus("답변 중입니다. Realtime 연결 전에는 브라우저가 분석 제어를 시작하지 않습니다.");
  appendLog("candidate answer turn started; browser analysis control disabled");
}

async function finishAnswerAndRequestNextQuestion() {
  if (activeRealtimeSession) {
    await finishRealtimeAnswerAndRequestNextQuestion();
    return;
  }
  micEnabled = false;
  syncMediaUi();
  await applyMediaStateToRoom();
  await syncCameraPreviewForCameraState("legacy-answer-end-camera-preserve");
  renderTranscriptStatus("답변 종료. 브라우저 전사 주입 없이 다음 질문을 요청합니다.");
  lastAnswerTranscript = "브라우저 전사 주입 없음; 서버 분석 경계가 답변 evidence를 처리합니다.";
  lastAnalysisBlock = "";
  currentTurnIndex += 1;
  nextQuestionRequested = false;
  setAnswerTurnAvailability(false, "candidate answer ended; waiting for next interviewer question");
  requestNextQuestion("candidate-answer-ended-browser-clean-boundary");
}

async function toggleMic() {
  if (!micEnabled && !answerTurnAvailable) {
    appendLog("answer start blocked until interviewer question ends");
    return;
  }
  try {
    if (!micEnabled) {
      micEnabled = true;
      syncMediaUi();
      await applyMediaStateToRoom();
      await syncCameraPreviewForCameraState("answer-start-camera-preserve");
      await startAnswerCapture();
      return;
    }
    await finishAnswerAndRequestNextQuestion();
  } catch (error) {
    const message = errorMessage(error);
    micEnabled = false;
    syncMediaUi();
    await applyMediaStateToRoom().catch((stateError) => appendLog(`answer failure media state sync failed: ${errorMessage(stateError)}`));
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
    await syncCameraPreviewForCameraState("camera-toggle");
    await applyMediaStateToRoom();
  } catch (error) {
    const message = errorMessage(error);
    cameraEnabled = false;
    stopPreviewStream();
    syncMediaUi();
    setStatus(`media permission failed: ${message}`, "error");
    appendLog(`media permission failed: ${message}`);
  }
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
  const sessionLabel = payload.roomName || payload.sessionId || activeInterviewId;
  setStatus(`session created: ${sessionLabel}`, "idle");
  appendLog(`session created for ${sessionLabel}; tokens hidden; avatar remains deferred unless a verified avatar path is explicitly enabled`);
  renderAvatarSdkDegraded("avatar_session_deferred_unverified");
  return activeSession;
}

async function connectPrimaryTransport() {
  const session = activeSession ?? (await createSession());
  if (!isRealtimePrimary(session)) {
    appendLog("Realtime primary metadata missing; attempting API-brokered Realtime path and failing closed if unavailable");
  }
  await connectRealtimeRoom(session);
  await requestAvatarSession("primary-transport-connected");
  nextQuestionRequested = false;
  await requestRealtimeNextQuestion("realtime-connected-avatar-checked");
}

async function connectProductionRoomRoute() {
  if (!shouldAutoJoinRoom) {
    return;
  }
  try {
    await connectPrimaryTransport();
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
}

function leaveRoom() {
  const cleanupTasks = [disconnectAvatarRtc()];
  if (activeRealtimeSession) {
    cleanupTasks.push(disconnectRealtimeRoom());
  }
  Promise.allSettled(cleanupTasks).then((results) => {
    results.forEach((result) => {
      if (result.status === "rejected") {
        appendLog(`Realtime cleanup skipped: ${errorMessage(result.reason)}`);
      }
    });
  });
  setRoomMode("prejoin");
  setStatus("Realtime disconnected", "idle");
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
    await connectPrimaryTransport();
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
renderCoachFeedbackState("코치 피드백 대기", "답변 분석이 정리되면 코치 피드백이 표시됩니다.", []);
renderTranscriptStatus("OpenAI Realtime 전사와 bounded vision metadata를 analysis-engine에 전달한 뒤, API가 MMM 준비 후 다음 질문을 생성합니다.");
appendLog(`Interview Room ready for interview ${activeInterviewId}; use /api/sessions through Caddy for same-origin API access`);
connectProductionRoomRoute();
