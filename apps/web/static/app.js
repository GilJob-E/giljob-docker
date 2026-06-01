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
}

function renderTranscriptStatus(message) {
  if (transcriptBody) {
    transcriptBody.textContent = message;
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
    const response = await fetch("/ai/interview/next-question", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        interviewId: activeInterviewId,
        turnIndex: currentTurnIndex,
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
    setTimeout(() => {
      document.dispatchEvent(new CustomEvent("giljob:interviewer-question-ended", { detail: payload }));
    }, 800);
  } catch (error) {
    nextQuestionRequested = false;
    renderInterviewQuestion(null);
    if (interviewerMediaState) {
      interviewerMediaState.textContent = "질문 실패";
    }
    setStatus(`question request failed: ${error.message}`, "error");
    appendLog(`question request failed: ${error.message}`);
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

function startAnswerCapture() {
  renderTranscriptStatus("답변 중입니다. 전사는 GilJobE analysis-engine 연결 전까지 생성하지 않습니다.");
  appendLog("candidate answer turn started; STT boundary disabled pending GilJobE analysis-engine");
}

async function finishAnswerAndRequestNextQuestion() {
  micEnabled = false;
  await restartPreviewStream();
  await applyMediaStateToRoom();
  lastAnswerTranscript = "후보자 답변 전사는 GilJobE analysis-engine 연결 전까지 비활성화되어 있습니다.";
  renderTranscriptStatus("답변 종료. 전사는 다음 단계에서 GilJobE analysis-engine이 LiveKit track을 구독해 생성할 예정입니다.");
  currentTurnIndex += 1;
  nextQuestionRequested = false;
  setAnswerTurnAvailability(false, "candidate answer ended; waiting for next interviewer question");
  requestNextQuestion("candidate-answer-ended-no-stt");
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
      startAnswerCapture();
      return;
    }
    await finishAnswerAndRequestNextQuestion();
  } catch (error) {
    micEnabled = false;
    stopPreviewStream();
    syncMediaUi();
    setStatus(`answer turn failed: ${error.message}`, "error");
    appendLog(`answer turn failed: ${error.message}`);
  }
}

async function toggleCamera() {
  cameraEnabled = !cameraEnabled;
  try {
    await restartPreviewStream();
    await applyMediaStateToRoom();
  } catch (error) {
    micEnabled = false;
    cameraEnabled = false;
    stopPreviewStream();
    syncMediaUi();
    setStatus(`media permission failed: ${error.message}`, "error");
    appendLog(`media permission failed: ${error.message}`);
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
    body: JSON.stringify({ role }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.message || payload.error || `session request failed: HTTP ${response.status}`);
  }

  activeSession = payload;
  renderSessionSummary(activeSession);
  setStatus(`session created: ${payload.roomName}`, "idle");
  appendLog(`session created for room ${payload.roomName}; tokens hidden`);
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
  appendLog(`media publish failed after join; disconnecting room fail-closed: ${error.message}`);
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
    setRoomMode("prejoin");
    setStatus(error.message, "error");
    appendLog(`error: ${error.message}`);
    if (leaveButton) {
      leaveButton.disabled = true;
    }
  }
}

function leaveRoom() {
  if (!activeRoom) {
    return;
  }
  appendLog("leaving LiveKit room");
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
    setStatus(error.message, "error");
    appendLog(`error: ${error.message}`);
  }
});

previewButton?.addEventListener("click", async () => {
  try {
    await startPreview();
  } catch (error) {
    micEnabled = false;
    cameraEnabled = false;
    stopPreviewStream();
    syncMediaUi();
    setStatus(`media permission failed: ${error.message}`, "error");
    appendLog(`media permission failed: ${error.message}`);
  }
});

toggleMicButton?.addEventListener("click", toggleMic);
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
    setRoomMode("prejoin");
    setStatus(error.message, "error");
    appendLog(`error: ${error.message}`);
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
setContextDrawerOpen(false);
setRoomMode("prejoin");
setAnswerTurnAvailability(false);
syncMediaUi();
hydrateProductionRoutes();
renderTranscriptStatus("로컬 STT 경계는 제거되었습니다. GilJobE analysis-engine 연결 전까지 답변 전사는 생성하지 않습니다.");
appendLog(`Interview Room ready for interview ${activeInterviewId}; use /api/sessions through Caddy for same-origin API access`);
autoJoinRoomRoute();
