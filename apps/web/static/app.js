import { Room, RoomEvent } from "./vendor/livekit-client/dist/livekit-client.esm.mjs";

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

let activeSession = null;
let activeRoom = null;
let localPreviewStream = null;
let micEnabled = false;
let cameraEnabled = false;
const activeInterviewId = interviewIdFromPath(window.location.pathname);

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

function appendLog(message) {
  const timestamp = new Date().toISOString();
  logEl.textContent = `${timestamp} ${redactSensitiveText(message)}\n${logEl.textContent}`;
}

function setStatus(message, state = "idle") {
  statusEl.textContent = redactSensitiveText(message);
  statusEl.dataset.state = state;
}

function setRoomMode(mode) {
  roomShell.dataset.mode = mode;
  const labels = {
    prejoin: "Pre-join",
    connecting: "Connecting",
    connected: "Connected",
  };
  roomStateEl.textContent = labels[mode] ?? mode;
}

function valueOrDash(value) {
  return value ? String(value) : "-";
}

function renderSessionSummary(session) {
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
  button.setAttribute("aria-pressed", String(isPressed));
  button.textContent = isPressed ? onLabel : offLabel;
  button.dataset.enabled = String(isPressed);
}

function syncMediaUi() {
  publishMediaInput.checked = micEnabled || cameraEnabled;
  setButtonPressed(toggleMicButton, micEnabled, "Mic on", "Mic off");
  setButtonPressed(toggleCameraButton, cameraEnabled, "Camera on", "Camera off");
  const hasCameraPreview = Boolean(cameraEnabled && localPreviewStream);
  localPreviewVideo.hidden = !hasCameraPreview;
  candidateRoomVideo.hidden = !hasCameraPreview;
  previewPlaceholder.hidden = hasCameraPreview;
  candidatePlaceholder.hidden = hasCameraPreview;
  candidateMediaState.textContent = `Mic ${micEnabled ? "on" : "off"} · Camera ${cameraEnabled ? "on" : "off"}`;
  permissionNote.textContent = hasCameraPreview
    ? "카메라 프리뷰는 브라우저 로컬에서만 표시됩니다."
    : "입장 전 카메라/마이크를 켜서 권한과 프리뷰를 확인할 수 있습니다.";
}

function stopPreviewStream() {
  if (!localPreviewStream) {
    return;
  }
  localPreviewStream.getTracks().forEach((track) => track.stop());
  localPreviewStream = null;
  localPreviewVideo.srcObject = null;
  candidateRoomVideo.srcObject = null;
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
    localPreviewVideo.srcObject = stream;
    candidateRoomVideo.srcObject = stream;
  }
  syncMediaUi();
  setStatus("preview ready", activeRoom ? "connected" : "idle");
  appendLog(`local preview ready: mic ${micEnabled ? "on" : "off"}, camera ${cameraEnabled ? "on" : "off"}; tokens hidden`);
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
  appendLog(`room media updated: mic ${micEnabled ? "on" : "off"}, camera ${cameraEnabled ? "on" : "off"}`);
}

async function toggleMic() {
  micEnabled = !micEnabled;
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
  const endpoint = apiEndpointInput.value.trim() || "/api/sessions";
  const role = roleInput.value.trim() || "candidate";
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
      leaveButton.disabled = false;
      joinButton.disabled = true;
      appendLog("LiveKit connected");
    })
    .on(RoomEvent.Disconnected, (reason) => {
      setRoomMode("prejoin");
      setStatus(`LiveKit disconnected${reason ? `: ${reason}` : ""}`, "idle");
      leaveButton.disabled = true;
      joinButton.disabled = false;
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
  appendLog(`publishing local media: mic ${micEnabled ? "on" : "off"}, camera ${cameraEnabled ? "on" : "off"}`);
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
  leaveButton.disabled = true;
  joinButton.disabled = false;
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

function leaveRoom() {
  if (!activeRoom) {
    return;
  }
  appendLog("leaving LiveKit room");
  activeRoom.disconnect();
  activeRoom = null;
  leaveButton.disabled = true;
  joinButton.disabled = false;
}

createButton.addEventListener("click", async () => {
  try {
    await createSession();
  } catch (error) {
    setStatus(error.message, "error");
    appendLog(`error: ${error.message}`);
  }
});

previewButton.addEventListener("click", async () => {
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

toggleMicButton.addEventListener("click", toggleMic);
toggleCameraButton.addEventListener("click", toggleCamera);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await joinRoom();
  } catch (error) {
    setRoomMode("prejoin");
    setStatus(error.message, "error");
    appendLog(`error: ${error.message}`);
    leaveButton.disabled = true;
    joinButton.disabled = false;
  }
});

leaveButton.addEventListener("click", leaveRoom);

renderSessionSummary(null);
setRoomMode("prejoin");
syncMediaUi();
hydrateProductionRoutes();
appendLog(`Interview Room ready for interview ${activeInterviewId}; use /api/sessions through Caddy for same-origin API access`);
