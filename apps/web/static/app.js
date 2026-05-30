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

let activeSession = null;
let activeRoom = null;

function redactSensitiveText(value) {
  return String(value)
    .replace(/access_token=[^'"\s&]+/g, "access_token=<redacted>")
    .replace(/join_request=[^'"\s&]+/g, "join_request=<redacted>")
    .replace(/eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+/g, "<jwt-redacted>")
    .replace(/gj_(session|report)_[A-Za-z0-9._-]+/g, "gj_$1_<redacted>");
}

function appendLog(message) {
  const timestamp = new Date().toISOString();
  logEl.textContent = `${timestamp} ${redactSensitiveText(message)}\n${logEl.textContent}`;
}

function setStatus(message, state = "idle") {
  statusEl.textContent = redactSensitiveText(message);
  statusEl.dataset.state = state;
}

function valueOrDash(value) {
  return value ? String(value) : "-";
}

function renderSessionSummary(session) {
  const livekit = session?.livekit ?? {};
  const rows = [
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
      setStatus("LiveKit connected", "connected");
      leaveButton.disabled = false;
      joinButton.disabled = true;
      appendLog("LiveKit connected");
    })
    .on(RoomEvent.Disconnected, (reason) => {
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
  if (!publishMediaInput.checked) {
    appendLog("media publish skipped (default smoke mode)");
    return;
  }
  appendLog("requesting browser microphone/camera permissions");
  await room.localParticipant.setMicrophoneEnabled(true);
  await room.localParticipant.setCameraEnabled(true);
  appendLog("local microphone/camera publish requested");
}

async function joinRoom() {
  const session = activeSession ?? (await createSession());
  const { url, token } = sessionLiveKitConfig(session);
  if (activeRoom) {
    activeRoom.disconnect();
  }

  setStatus("connecting to LiveKit...", "connecting");
  activeRoom = new Room();
  bindRoomEvents(activeRoom);
  appendLog(`connecting to ${url} as ${session.livekit.participantIdentity}; token hidden`);
  await activeRoom.connect(url, token);
  await maybePublishLocalMedia(activeRoom);
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

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await joinRoom();
  } catch (error) {
    setStatus(error.message, "error");
    appendLog(`error: ${error.message}`);
    leaveButton.disabled = true;
    joinButton.disabled = false;
  }
});

leaveButton.addEventListener("click", leaveRoom);

renderSessionSummary(null);
appendLog("UI ready; use /api/sessions through Caddy for same-origin API access");
