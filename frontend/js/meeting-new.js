/** New meeting page: metadata, consent, record/upload. */

import { apiRequest, getStoredEmail, getStoredToken } from "./api.js";
import { requireAuth, signOut } from "./auth.js";
import { MeetingRecorder, extensionForMime } from "./recorder.js";
import { initThemeToggle } from "./theme.js";
import { setText } from "./ui.js";

const ALLOWED_EXTENSIONS = [".webm", ".wav", ".mp3", ".m4a", ".mp4", ".mpeg", ".mpga"];
const MAX_BYTES = 262144000;

let recorder = null;
let recordedBlob = null;
let selectedFile = null;
let timerId = null;

function showError(message) {
  const el = document.getElementById("page-error");
  if (!el) return;
  setText(el, message);
  el.hidden = !message;
}

function formatTimer(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = String(Math.floor(total / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function setRecorderButtons(state) {
  document.getElementById("btn-start").disabled = state === "recording" || state === "paused";
  document.getElementById("btn-pause").disabled = state !== "recording";
  document.getElementById("btn-resume").disabled = state !== "paused";
  document.getElementById("btn-stop").disabled = state !== "recording" && state !== "paused";
  document.getElementById("btn-discard").disabled = state === "idle";
}

function ensureConsent() {
  return document.getElementById("consent").checked;
}

async function uploadBlob(meetingId, blob, source, filename) {
  const mimeType = blob.type || "audio/webm";
  const initiate = await apiRequest(`/api/v1/meetings/${meetingId}/recordings/initiate`, {
    method: "POST",
    body: JSON.stringify({
      original_filename: filename,
      mime_type: mimeType,
      size_bytes: blob.size,
      source,
      sha256: null,
    }),
  });

  const putResponse = await fetch(initiate.upload_url, {
    method: "PUT",
    headers: {
      "Content-Type": mimeType,
      "X-Upload-Token": initiate.upload_token,
      Authorization: `Bearer ${getStoredToken()}`,
    },
    body: blob,
  });
  if (!putResponse.ok) {
    throw new Error("Audio upload failed.");
  }

  return apiRequest(`/api/v1/meetings/${meetingId}/recordings/complete`, {
    method: "POST",
    body: JSON.stringify({
      upload_token: initiate.upload_token,
      storage_key: initiate.storage_key,
      size_bytes: blob.size,
      sha256: null,
    }),
  });
}

async function createMeetingFromForm() {
  const form = document.getElementById("meta-form");
  const title = form.title.value.trim();
  if (!title) throw new Error("Title is required.");
  if (!ensureConsent()) throw new Error("Confirm participant consent before continuing.");
  return apiRequest("/api/v1/meetings", {
    method: "POST",
    body: JSON.stringify({
      title,
      meeting_type: form.meeting_type.value,
      language: form.language.value || null,
      consent_confirmed: true,
      participants: [],
    }),
  });
}

async function submitAudio(blob, source, filename) {
  showError("");
  const status = document.getElementById("upload-status");
  setText(status, "Creating meeting…");
  const meeting = await createMeetingFromForm();
  setText(status, "Uploading audio…");
  const recording = await uploadBlob(meeting.id, blob, source, filename);
  setText(status, `Uploaded (${recording.id}). Meeting status is now uploaded.`);
  window.location.href = "/app";
}

function validateFile(file) {
  if (!file) return "Choose an audio file.";
  if (file.size <= 0) return "File is empty.";
  if (file.size > MAX_BYTES) return "File exceeds the 250 MB limit.";
  const lower = file.name.toLowerCase();
  if (!ALLOWED_EXTENSIONS.some((ext) => lower.endsWith(ext))) {
    return "Unsupported file extension.";
  }
  return "";
}

function bindRecorder() {
  recorder = new MeetingRecorder({
    onStateChange: (state) => {
      setText(document.getElementById("recorder-state"), state);
      setRecorderButtons(state);
    },
    onError: (error) => {
      showError(error.message || "Microphone error.");
      setRecorderButtons("idle");
    },
    onLevel: (level) => {
      const meter = document.getElementById("level-meter");
      if (meter) meter.value = level;
    },
  });

  document.getElementById("btn-start").addEventListener("click", async () => {
    showError("");
    if (!ensureConsent()) {
      showError("Confirm consent before recording.");
      return;
    }
    recordedBlob = null;
    selectedFile = null;
    const useTab = document.getElementById("tab-audio")?.checked;
    await recorder.start({ source: useTab ? "tab" : "mic" });
    timerId = setInterval(() => {
      setText(document.getElementById("timer"), formatTimer(recorder.elapsedMs()));
    }, 250);
  });

  document.getElementById("btn-pause").addEventListener("click", () => recorder.pause());
  document.getElementById("btn-resume").addEventListener("click", () => recorder.resume());
  document.getElementById("btn-stop").addEventListener("click", async () => {
    recordedBlob = await recorder.stop();
    clearInterval(timerId);
    const preview = document.getElementById("preview");
    preview.src = URL.createObjectURL(recordedBlob);
    preview.hidden = false;
    setText(document.getElementById("upload-status"), "Recording ready to upload.");
  });
  document.getElementById("btn-discard").addEventListener("click", async () => {
    await recorder.discard();
    clearInterval(timerId);
    recordedBlob = null;
    document.getElementById("preview").hidden = true;
    setText(document.getElementById("timer"), "00:00");
    setText(document.getElementById("upload-status"), "");
  });
}

function bindUpload() {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");

  const assignFile = (file) => {
    const error = validateFile(file);
    if (error) {
      showError(error);
      return;
    }
    selectedFile = file;
    recordedBlob = null;
    showError("");
    setText(document.getElementById("upload-status"), `Selected ${file.name}`);
  };

  dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropzone.classList.add("is-dragover");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("is-dragover"));
  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-dragover");
    const file = event.dataTransfer?.files?.[0];
    if (file) assignFile(file);
  });
  fileInput.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    if (file) assignFile(file);
  });

  document.getElementById("btn-upload").addEventListener("click", async () => {
    try {
      if (recordedBlob) {
        const ext = extensionForMime(recordedBlob.type || "audio/webm");
        await submitAudio(recordedBlob, "browser", `recording.${ext}`);
        return;
      }
      if (selectedFile) {
        await submitAudio(selectedFile, "upload", selectedFile.name);
        return;
      }
      showError("Record audio or choose a file first.");
    } catch (error) {
      showError(error.message || "Upload failed.");
      setText(document.getElementById("upload-status"), "");
    }
  });
}

function init() {
  if (!requireAuth()) return;
  initThemeToggle();
  setText(document.getElementById("user-email"), getStoredEmail() || "Signed in");
  document.getElementById("sign-out")?.addEventListener("click", signOut);
  setRecorderButtons("idle");
  bindRecorder();
  bindUpload();
}

init();
