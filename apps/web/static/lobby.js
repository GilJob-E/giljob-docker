// GilJob v2 lobby device check.
//
// Pre-join readiness for the production interview flow: the candidate confirms
// session components and directly verifies microphone input level and camera
// preview before entering the room. Media is user-initiated (never auto-started)
// and stays local to this browser; nothing is uploaded and no tokens are involved.

const micTestButton = document.getElementById("mic-test");
const micDeviceSelect = document.getElementById("mic-device");
const micMeterFill = document.getElementById("mic-meter-fill");
const micStatus = document.getElementById("mic-status");
const camTestButton = document.getElementById("cam-test");
const camVideo = document.getElementById("cam-video");
const camPlaceholder = document.getElementById("cam-placeholder");
const camStatus = document.getElementById("cam-status");
const readinessStatus = document.getElementById("lobby-readiness-status");
const enterRoom = document.getElementById("enter-room");
const enterRoomHint = document.getElementById("enter-room-hint");

// Mirror app.js redaction so any device error text stays token-safe.
function redactSensitiveText(value) {
  return String(value)
    .replace(/access_token=[^'"\s&]+/g, "access_token=<redacted>")
    .replace(/eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+/g, "<jwt-redacted>")
    .replace(/gj_(session|report)_[A-Za-z0-9._-]+/g, "gj_$1_<redacted>");
}

function setState(el, label, state) {
  if (!el) return;
  el.textContent = label;
  if (state) {
    el.dataset.state = state;
  } else {
    delete el.dataset.state;
  }
}

function describeMediaError(error) {
  const name = error && error.name ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") return "권한 거부됨";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "장치 없음";
  if (name === "NotReadableError") return "장치 사용 중";
  return "오류";
}

function mediaSupported() {
  return Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}

function updateReadiness() {
  const micOk = micStatus.dataset.state === "ok";
  const camOk = camStatus.dataset.state === "ok";
  if (micOk && camOk) {
    setState(readinessStatus, "점검 완료", "connected");
  } else if (micOk || camOk) {
    setState(readinessStatus, "점검 중", "connecting");
  } else {
    setState(readinessStatus, "점검 전", null);
  }
  updateEnterRoom(micOk && camOk);
}

// Gate room entry: keep "방으로 입장" disabled (grey) until both mic and camera
// are verified usable, then enable it.
function updateEnterRoom(ready) {
  if (!enterRoom) return;
  enterRoom.setAttribute("aria-disabled", String(!ready));
  enterRoom.tabIndex = ready ? 0 : -1;
  if (enterRoomHint) {
    enterRoomHint.textContent = ready
      ? "입장 준비 완료 · 방으로 입장할 수 있습니다."
      : "마이크와 카메라를 모두 점검하면 입장할 수 있습니다.";
    enterRoomHint.dataset.ready = String(ready);
  }
}

enterRoom?.addEventListener("click", (event) => {
  if (enterRoom.getAttribute("aria-disabled") === "true") {
    event.preventDefault();
  }
});

// ── Microphone ────────────────────────────────────────────────────────────
let micStream = null;
let audioContext = null;
let analyser = null;
let meterRaf = 0;
let micActive = false;

function stopMic() {
  micActive = false;
  if (meterRaf) {
    cancelAnimationFrame(meterRaf);
    meterRaf = 0;
  }
  if (audioContext) {
    audioContext.close().catch(() => {});
    audioContext = null;
  }
  analyser = null;
  if (micStream) {
    micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
  }
  micMeterFill.style.width = "0%";
  micTestButton.setAttribute("aria-pressed", "false");
  micTestButton.textContent = "마이크 테스트 시작";
}

function runMeter() {
  if (!analyser) return;
  const buffer = new Uint8Array(analyser.fftSize);
  const tick = () => {
    if (!analyser) return;
    analyser.getByteTimeDomainData(buffer);
    let sumSquares = 0;
    for (let i = 0; i < buffer.length; i += 1) {
      const sample = (buffer[i] - 128) / 128;
      sumSquares += sample * sample;
    }
    const rms = Math.sqrt(sumSquares / buffer.length);
    // Scale RMS to a usable 0-100 range; speech rarely fills the full scale.
    const level = Math.min(100, Math.round(rms * 320));
    micMeterFill.style.width = `${level}%`;
    setState(micStatus, level > 8 ? "입력 감지됨" : "조용함", "ok");
    meterRaf = requestAnimationFrame(tick);
  };
  meterRaf = requestAnimationFrame(tick);
}

async function populateMicDevices() {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const inputs = devices.filter((device) => device.kind === "audioinput");
    if (!inputs.length) return;
    const current = micStream?.getAudioTracks()?.[0]?.getSettings()?.deviceId;
    micDeviceSelect.replaceChildren();
    inputs.forEach((device, index) => {
      const option = document.createElement("option");
      option.value = device.deviceId;
      option.textContent = device.label || `마이크 ${index + 1}`;
      if (device.deviceId && device.deviceId === current) option.selected = true;
      micDeviceSelect.appendChild(option);
    });
    micDeviceSelect.disabled = false;
  } catch {
    // Device enumeration is best-effort; the meter still works without labels.
  }
}

async function startMic(deviceId) {
  if (!mediaSupported()) {
    setState(micStatus, "지원 안 됨", "error");
    return;
  }
  setState(micStatus, "권한 요청 중", "connecting");
  try {
    const constraints = deviceId
      ? { audio: { deviceId: { exact: deviceId } } }
      : { audio: true };
    micStream = await navigator.mediaDevices.getUserMedia(constraints);
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const source = audioContext.createMediaStreamSource(micStream);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    micActive = true;
    micTestButton.setAttribute("aria-pressed", "true");
    micTestButton.textContent = "마이크 테스트 중지";
    setState(micStatus, "입력 대기", "ok");
    await populateMicDevices();
    runMeter();
  } catch (error) {
    stopMic();
    setState(micStatus, describeMediaError(error), "error");
    if (typeof console !== "undefined") {
      console.warn(`lobby mic check: ${redactSensitiveText(error?.message ?? error)}`);
    }
  }
  updateReadiness();
}

micTestButton?.addEventListener("click", async () => {
  if (micActive) {
    stopMic();
    setState(micStatus, "중지됨", null);
    updateReadiness();
    return;
  }
  await startMic(micDeviceSelect.disabled ? undefined : micDeviceSelect.value);
});

micDeviceSelect?.addEventListener("change", async () => {
  if (!micActive) return;
  const deviceId = micDeviceSelect.value;
  stopMic();
  await startMic(deviceId);
});

// ── Camera ────────────────────────────────────────────────────────────────
let camStream = null;
let camActive = false;

function stopCamera() {
  camActive = false;
  if (camStream) {
    camStream.getTracks().forEach((track) => track.stop());
    camStream = null;
  }
  camVideo.srcObject = null;
  camVideo.hidden = true;
  camPlaceholder.hidden = false;
  camTestButton.setAttribute("aria-pressed", "false");
  camTestButton.textContent = "카메라 미리보기 켜기";
}

async function startCamera() {
  if (!mediaSupported()) {
    setState(camStatus, "지원 안 됨", "error");
    return;
  }
  setState(camStatus, "권한 요청 중", "connecting");
  try {
    camStream = await navigator.mediaDevices.getUserMedia({ video: true });
    camVideo.srcObject = camStream;
    camVideo.hidden = false;
    camPlaceholder.hidden = true;
    camActive = true;
    camTestButton.setAttribute("aria-pressed", "true");
    camTestButton.textContent = "카메라 미리보기 끄기";
    setState(camStatus, "미리보기 중", "ok");
  } catch (error) {
    stopCamera();
    setState(camStatus, describeMediaError(error), "error");
    if (typeof console !== "undefined") {
      console.warn(`lobby camera check: ${redactSensitiveText(error?.message ?? error)}`);
    }
  }
  updateReadiness();
}

camTestButton?.addEventListener("click", async () => {
  if (camActive) {
    stopCamera();
    setState(camStatus, "꺼짐", null);
    updateReadiness();
    return;
  }
  await startCamera();
});

// Release devices when leaving the lobby (entering the room or navigating away).
window.addEventListener("pagehide", () => {
  stopMic();
  stopCamera();
});

if (!mediaSupported()) {
  setState(micStatus, "지원 안 됨", "error");
  setState(camStatus, "지원 안 됨", "error");
}

// ── Session setup summary ─────────────────────────────────────────────────
(function restoreSessionSetup() {
  let setup = {};
  try {
    const raw = sessionStorage.getItem("giljob_new_setup");
    if (raw) setup = JSON.parse(raw);
  } catch (_) {}

  const resumeEl = document.getElementById("summary-resume");
  const jobEl = document.getElementById("summary-job");
  const interviewerEl = document.getElementById("summary-interviewer");

  if (resumeEl && setup.cvFileName) resumeEl.textContent = setup.cvFileName;
  if (jobEl) {
    if (setup.jobUrl) {
      jobEl.textContent = setup.jobUrl;
    }
  }
  if (interviewerEl && setup.interviewer) interviewerEl.textContent = setup.interviewer;
}());
