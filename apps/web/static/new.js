"use strict";

// interview-new setup form: resume drag-and-drop + filename feedback.
// Pure front interaction — no upload, no network, no token handling here.
// The actual session/id creation stays a backend (/api/sessions) concern.

const fileInput = document.querySelector("#resume-file");
const dropzone = document.querySelector(".upload-dropzone");
const primaryLabel = dropzone?.querySelector(".upload-primary");
const secondaryLabel = dropzone?.querySelector(".upload-secondary");

const ACCEPTED_EXTENSIONS = [".pdf", ".doc", ".docx"];
const MAX_BYTES = 10 * 1024 * 1024;

const DEFAULT_PRIMARY = "파일을 끌어다 놓거나 클릭해 선택";
const DEFAULT_SECONDARY = "아직 업로드한 파일이 없습니다";

function hasAllowedExtension(name) {
  const lower = name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

function formatSize(bytes) {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  }
  if (bytes >= 1024) {
    return `${Math.round(bytes / 1024)}KB`;
  }
  return `${bytes}B`;
}

function setLabels(primary, secondary) {
  if (primaryLabel) {
    primaryLabel.textContent = primary;
  }
  if (secondaryLabel) {
    secondaryLabel.textContent = secondary;
  }
}

function renderFile(file) {
  if (!dropzone) {
    return;
  }
  if (!file) {
    dropzone.dataset.state = "empty";
    setLabels(DEFAULT_PRIMARY, DEFAULT_SECONDARY);
    return;
  }
  if (!hasAllowedExtension(file.name)) {
    dropzone.dataset.state = "error";
    setLabels("지원하지 않는 형식입니다", "PDF, DOC, DOCX 파일만 업로드할 수 있습니다");
    return;
  }
  if (file.size > MAX_BYTES) {
    dropzone.dataset.state = "error";
    setLabels("파일이 너무 큽니다", "최대 10MB까지 업로드할 수 있습니다");
    return;
  }
  dropzone.dataset.state = "filled";
  setLabels(file.name, `${formatSize(file.size)} · 교체하려면 클릭하거나 다시 끌어다 놓으세요`);
}

function canAccept(file) {
  return hasAllowedExtension(file.name) && file.size <= MAX_BYTES;
}

function assignToInput(file) {
  if (!fileInput) {
    return;
  }
  try {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    fileInput.files = transfer.files;
  } catch (_error) {
    // DataTransfer can be unavailable in some browsers; keep the visual
    // feedback even if we cannot back-fill the native input selection.
  }
}

const jobUrlInput = document.querySelector("#job-url");
const interviewerSelect = document.querySelector("#interviewer-select");
const submitLink = document.querySelector(".actions .button-primary");

if (submitLink) {
  submitLink.addEventListener("click", () => {
    const cvFileName = fileInput && fileInput.files && fileInput.files[0]
      ? fileInput.files[0].name
      : "";
    const jobUrl = jobUrlInput ? jobUrlInput.value.trim() : "";
    const interviewer = interviewerSelect
      ? (interviewerSelect.options[interviewerSelect.selectedIndex]?.text || "")
      : "";
    try {
      sessionStorage.setItem("giljob_new_setup", JSON.stringify({ cvFileName, jobUrl, interviewer }));
    } catch (_) {}
  });
}

if (fileInput && dropzone) {
  fileInput.addEventListener("change", () => {
    renderFile(fileInput.files && fileInput.files[0] ? fileInput.files[0] : null);
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.dataset.drag = "over";
    });
  });

  ["dragleave", "dragend"].forEach((eventName) => {
    dropzone.addEventListener(eventName, () => {
      delete dropzone.dataset.drag;
    });
  });

  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    delete dropzone.dataset.drag;
    const file = event.dataTransfer && event.dataTransfer.files ? event.dataTransfer.files[0] : null;
    if (!file) {
      return;
    }
    if (canAccept(file)) {
      assignToInput(file);
    }
    renderFile(file);
  });
}
