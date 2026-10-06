/** Meeting workspace: audio sync, search, rename, export, delete, shortcuts. */

import { apiRequest, getStoredEmail, isReadOnlySession } from "./api.js";
import { requireAuth, signOut } from "./auth.js";
import { initThemeToggle } from "./theme.js";
import { clearState, renderState, setText, showError as setErrorBanner } from "./ui.js";

const meetingId = window.location.pathname.split("/").filter(Boolean).pop();
let segments = [];
let activeSegmentId = null;

function showError(message) {
  setErrorBanner(document.getElementById("page-error"), message);
}

function formatMs(ms) {
  const total = Math.floor(ms / 1000);
  const m = String(Math.floor(total / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function downloadText(filename, content, contentType) {
  const blob = new Blob([content], { type: contentType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function focusSegment(segmentId) {
  if (!segmentId) return;
  activeSegmentId = segmentId;
  const segment = segments.find((row) => row.id === segmentId);
  const player = document.getElementById("player");
  if (segment && player) {
    player.currentTime = segment.start_ms / 1000;
  }
  renderTranscript(segments, document.getElementById("search-input")?.value || "");
  document
    .querySelector(`[data-segment-id="${segmentId}"]`)
    ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function stepSegment(delta) {
  if (!segments.length) return;
  const index = Math.max(
    0,
    segments.findIndex((row) => row.id === activeSegmentId),
  );
  const nextIndex = Math.min(segments.length - 1, Math.max(0, (index < 0 ? 0 : index) + delta));
  focusSegment(segments[nextIndex].id);
  const player = document.getElementById("player");
  if (player && !player.paused) player.play();
}

function togglePlayPause() {
  const player = document.getElementById("player");
  if (!player?.src) return;
  if (player.paused) player.play();
  else player.pause();
}

function toggleShortcutHelp() {
  const overlay = document.getElementById("shortcut-overlay");
  if (!overlay) return;
  overlay.hidden = !overlay.hidden;
  if (!overlay.hidden) {
    document.getElementById("shortcut-close")?.focus();
  }
}

function isTypingTarget(target) {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

function installShortcuts() {
  document.addEventListener("keydown", (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const typing = isTypingTarget(event.target);

    if (event.key === "?" && !typing) {
      event.preventDefault();
      toggleShortcutHelp();
      return;
    }
    if (event.key === "Escape") {
      const overlay = document.getElementById("shortcut-overlay");
      if (overlay && !overlay.hidden) {
        overlay.hidden = true;
        return;
      }
    }
    if (typing) return;

    if (event.key === "j" || event.key === "J") {
      event.preventDefault();
      stepSegment(1);
    } else if (event.key === "k" || event.key === "K") {
      event.preventDefault();
      stepSegment(-1);
    } else if (event.key === " ") {
      event.preventDefault();
      togglePlayPause();
    } else if (event.key === "/") {
      event.preventDefault();
      document.getElementById("search-input")?.focus();
    }
  });

  document.getElementById("shortcut-close")?.addEventListener("click", () => {
    const overlay = document.getElementById("shortcut-overlay");
    if (overlay) overlay.hidden = true;
  });
  document.getElementById("btn-shortcuts")?.addEventListener("click", () => toggleShortcutHelp());
  document.getElementById("shortcut-overlay")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) {
      event.currentTarget.hidden = true;
    }
  });
}

function renderTranscript(items, highlightQuery = "") {
  const list = document.getElementById("transcript-list");
  const emptyHost = document.getElementById("transcript-empty");
  list.replaceChildren();
  const q = highlightQuery.trim().toLowerCase();

  if (!items.length) {
    renderState(emptyHost, {
      variant: "empty",
      title: "No transcript yet",
      body: "Process the meeting from the dashboard to generate a speaker-aware transcript.",
      actionHref: "/app",
      actionLabel: "Back to dashboard",
    });
    return;
  }
  clearState(emptyHost);

  for (const item of items) {
    const li = document.createElement("li");
    li.className = "meeting-item transcript-segment";
    li.dataset.segmentId = item.id;
    if (item.id === activeSegmentId) li.classList.add("is-active");

    const who = document.createElement("button");
    who.type = "button";
    who.className = "button-quiet";
    const speakerName = item.speaker.display_name || item.speaker.label;
    who.textContent = `${formatMs(item.start_ms)} · ${speakerName}`;
    who.addEventListener("click", () => {
      const player = document.getElementById("player");
      player.currentTime = item.start_ms / 1000;
      player.play();
      activeSegmentId = item.id;
      renderTranscript(segments, document.getElementById("search-input").value);
    });

    const text = document.createElement("p");
    text.className = "meeting-meta";
    text.textContent = item.text;
    if (q && item.text.toLowerCase().includes(q)) {
      li.classList.add("is-match");
    }

    li.append(who, text);
    if (!isReadOnlySession()) {
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "button-quiet";
      edit.textContent = "Edit text";
      edit.addEventListener("click", async () => {
        const next = window.prompt("Segment text", item.text);
        if (!next || next === item.text) return;
        try {
          await apiRequest(`/api/v1/meetings/${meetingId}/transcript/segments/${item.id}`, {
            method: "PATCH",
            body: JSON.stringify({ text: next }),
          });
          await loadTranscript();
        } catch (error) {
          showError(error.message || "Could not edit segment.");
        }
      });
      li.append(edit);
    }

    list.append(li);
  }
}

function syncActiveSegment() {
  const player = document.getElementById("player");
  const ms = Math.floor(player.currentTime * 1000);
  const current = segments.find((s) => ms >= s.start_ms && ms < s.end_ms);
  const nextId = current?.id || null;
  if (nextId === activeSegmentId) return;
  activeSegmentId = nextId;
  renderTranscript(segments, document.getElementById("search-input").value);
  if (!activeSegmentId) return;
  const node = document.querySelector(`[data-segment-id="${activeSegmentId}"]`);
  node?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

async function loadMeeting() {
  const meeting = await apiRequest(`/api/v1/meetings/${meetingId}`);
  setText(document.getElementById("meeting-title"), meeting.title);
  setText(
    document.getElementById("meeting-meta"),
    `${meeting.status} · ${meeting.meeting_type} · ${meeting.language || "auto"}`,
  );
  return meeting;
}

async function loadAudio() {
  const status = document.getElementById("audio-status");
  const emptyHost = document.getElementById("audio-empty");
  setText(status, "Loading audio…");
  try {
    const recordings = await apiRequest(`/api/v1/meetings/${meetingId}/recordings`);
    if (!recordings.length) {
      setText(status, "");
      renderState(emptyHost, {
        variant: "empty",
        title: "No audio on this meeting",
        body: "Upload a recording from New meeting, then process it.",
        actionHref: "/meetings/new",
        actionLabel: "Upload audio",
      });
      return;
    }
    clearState(emptyHost);
    const playback = await apiRequest(
      `/api/v1/meetings/${meetingId}/recordings/${recordings[0].id}/playback-url`,
    );
    const player = document.getElementById("player");
    player.src = playback.url;
    setText(status, `Loaded ${recordings[0].mime_type} (${recordings[0].size_bytes} bytes)`);
  } catch (error) {
    setText(status, "");
    renderState(emptyHost, {
      variant: "error",
      title: "Could not load audio",
      body: error.message || "Playback URL failed.",
      actionLabel: "Retry",
      onAction: () => void loadAudio(),
    });
  }
}

async function loadTranscript() {
  const emptyHost = document.getElementById("transcript-empty");
  renderState(emptyHost, {
    variant: "loading",
    title: "Loading transcript…",
  });
  try {
    const data = await apiRequest(`/api/v1/meetings/${meetingId}/transcript?limit=200`);
    segments = data.items || [];
    renderTranscript(segments);
  } catch (error) {
    renderState(emptyHost, {
      variant: "error",
      title: "Transcript unavailable",
      body: error.message || "Could not load transcript.",
      actionLabel: "Retry",
      onAction: () => void loadTranscript(),
    });
  }
}

async function loadInsights() {
  const summaryEl = document.getElementById("insight-summary");
  const decisionsEl = document.getElementById("insight-decisions");
  const actionsEl = document.getElementById("insight-actions");
  const emptyHost = document.getElementById("insights-empty");
  renderState(emptyHost, { variant: "loading", title: "Loading insights…" });
  try {
    const [insights, actions] = await Promise.all([
      apiRequest(`/api/v1/meetings/${meetingId}/insights`),
      apiRequest(`/api/v1/meetings/${meetingId}/actions`),
    ]);
    clearState(emptyHost);
    summaryEl.replaceChildren();
    const one = document.createElement("p");
    one.textContent = insights.one_sentence_summary;
    const exec = document.createElement("p");
    exec.className = "meeting-meta";
    exec.textContent = insights.executive_summary;
    summaryEl.append(one, exec);

    decisionsEl.replaceChildren();
    for (const decision of insights.decisions || []) {
      const li = document.createElement("li");
      li.className = "meeting-item";
      li.textContent = decision.text;
      decisionsEl.append(li);
    }
    if (!(insights.decisions || []).length) {
      const li = document.createElement("li");
      li.className = "meeting-meta";
      li.textContent = "No explicit decisions captured.";
      decisionsEl.append(li);
    }

    actionsEl.replaceChildren();
    for (const action of actions || []) {
      const li = document.createElement("li");
      li.className = "meeting-item";
      li.textContent = `[${action.status}] ${action.task}`;
      actionsEl.append(li);
    }
    if (!(actions || []).length) {
      const li = document.createElement("li");
      li.className = "meeting-meta";
      li.textContent = "No action items captured.";
      actionsEl.append(li);
    }
  } catch {
    summaryEl.replaceChildren();
    decisionsEl.replaceChildren();
    actionsEl.replaceChildren();
    renderState(emptyHost, {
      variant: "empty",
      title: "Insights not ready",
      body: "Process the meeting to generate summary, decisions, and actions.",
      actionHref: "/app",
      actionLabel: "Process from dashboard",
    });
  }
}

async function exportMeeting(format) {
  const result = await apiRequest(`/api/v1/meetings/${meetingId}/exports`, {
    method: "POST",
    body: JSON.stringify({
      format,
      include_transcript: true,
      include_participant_emails: false,
      include_audio_link: false,
    }),
  });
  downloadText(result.filename, result.content, result.content_type);
}

async function loadChat() {
  const list = document.getElementById("chat-list");
  const emptyHost = document.getElementById("chat-empty");
  if (!list) return;
  try {
    const data = await apiRequest(`/api/v1/meetings/${meetingId}/chat`);
    list.replaceChildren();
    const items = data.items || [];
    if (!items.length) {
      renderState(emptyHost, {
        variant: "empty",
        title: "No questions yet",
        body: "Ask about decisions, owners, or next steps — answers cite transcript timestamps.",
      });
      return;
    }
    clearState(emptyHost);
    for (const item of items) {
      const li = document.createElement("li");
      li.className = "meeting-item chat-message";
      const role = document.createElement("strong");
      role.textContent = item.role === "user" ? "You" : "Assistant";
      const body = document.createElement("p");
      body.className = "meeting-meta";
      body.textContent = item.content;
      li.append(role, body);
      if (item.role === "assistant" && item.answer_status) {
        const status = document.createElement("span");
        status.className = "meeting-meta";
        status.textContent = `Status: ${item.answer_status}`;
        li.append(status);
      }
      if (item.citations?.length) {
        const cites = document.createElement("div");
        cites.className = "button-row";
        for (const citation of item.citations) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "button-quiet";
          btn.textContent = `${formatMs(citation.start_ms)} · ${citation.speaker_name || "speaker"}`;
          btn.addEventListener("click", () => {
            const player = document.getElementById("player");
            player.currentTime = citation.start_ms / 1000;
            player.play();
            activeSegmentId = citation.segment_id;
            renderTranscript(segments, document.getElementById("search-input").value);
          });
          cites.append(btn);
        }
        li.append(cites);
      }
      list.append(li);
    }
    list.lastElementChild?.scrollIntoView({ block: "nearest" });
  } catch (error) {
    renderState(emptyHost, {
      variant: "error",
      title: "Chat history unavailable",
      body: error.message || "Could not load prior questions.",
      actionLabel: "Retry",
      onAction: () => void loadChat(),
    });
  }
}

async function askQuestion(question) {
  await apiRequest(`/api/v1/meetings/${meetingId}/questions`, {
    method: "POST",
    body: JSON.stringify({ question }),
  });
  await loadChat();
}

async function init() {
  if (!requireAuth()) return;
  initThemeToggle();
  installShortcuts();
  const readOnly = isReadOnlySession();
  setText(
    document.getElementById("user-email"),
    readOnly ? `${getStoredEmail() || "Demo"} · read-only` : getStoredEmail() || "Signed in",
  );
  document.getElementById("sign-out")?.addEventListener("click", signOut);

  if (readOnly) {
    document.body.classList.add("demo-readonly");
    const banner = document.getElementById("demo-banner");
    if (banner) banner.hidden = false;
    for (const id of ["btn-delete", "btn-share", "btn-rename", "rename-label", "rename-name"]) {
      document.getElementById(id)?.remove();
    }
  }

  const shellEmpty = document.getElementById("workspace-loading");
  renderState(shellEmpty, { variant: "loading", title: "Loading meeting workspace…" });

  try {
    await loadMeeting();
    clearState(shellEmpty);
    shellEmpty.hidden = true;
    await Promise.all([loadAudio(), loadTranscript(), loadInsights(), loadChat()]);
  } catch (error) {
    renderState(shellEmpty, {
      variant: "error",
      title: "Could not open this meeting",
      body: error.message || "The meeting may have been deleted.",
      actionHref: "/app",
      actionLabel: "Back to dashboard",
    });
    return;
  }

  document.getElementById("player").addEventListener("timeupdate", syncActiveSegment);

  let searchTimer = null;
  document.getElementById("search-input").addEventListener("input", (event) => {
    const value = event.target.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => {
      try {
        if (!value.trim()) {
          renderTranscript(segments);
          return;
        }
        const data = await apiRequest(
          `/api/v1/meetings/${meetingId}/transcript/search?q=${encodeURIComponent(value)}`,
        );
        const items = data.items || [];
        if (!items.length) {
          renderState(document.getElementById("transcript-empty"), {
            variant: "empty",
            title: "No matches",
            body: `Nothing matched “${value.trim()}”. Clear search or try another phrase.`,
          });
          document.getElementById("transcript-list").replaceChildren();
          return;
        }
        renderTranscript(items, value);
      } catch (error) {
        showError(error.message || "Search failed.");
      }
    }, 250);
  });

  document.getElementById("btn-rename")?.addEventListener("click", async () => {
    const speaker_label = document.getElementById("rename-label").value.trim();
    const display_name = document.getElementById("rename-name").value.trim();
    if (!speaker_label || !display_name) {
      showError("Provide speaker label and display name.");
      return;
    }
    try {
      await apiRequest(`/api/v1/meetings/${meetingId}/speakers/rename`, {
        method: "POST",
        body: JSON.stringify({ speaker_label, display_name }),
      });
      showError("");
      await loadTranscript();
    } catch (error) {
      showError(error.message || "Rename failed.");
    }
  });

  document
    .getElementById("btn-export-md")
    ?.addEventListener("click", () => exportMeeting("markdown"));
  document
    .getElementById("btn-export-json")
    ?.addEventListener("click", () => exportMeeting("json"));
  document
    .getElementById("btn-export-slack")
    ?.addEventListener("click", () => exportMeeting("slack"));
  document
    .getElementById("btn-export-notion")
    ?.addEventListener("click", () => exportMeeting("notion"));
  document
    .getElementById("btn-export-csv")
    ?.addEventListener("click", () => exportMeeting("actions_csv"));

  document.getElementById("btn-share")?.addEventListener("click", async () => {
    try {
      const link = await apiRequest(`/api/v1/meetings/${meetingId}/share-links`, {
        method: "POST",
        body: JSON.stringify({
          expires_in_hours: 72,
          include_transcript: true,
          include_insights: true,
        }),
      });
      setText(document.getElementById("share-status"), `Share URL: ${link.url}`);
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(link.url);
      }
      showError("");
    } catch (error) {
      showError(error.message || "Could not create share link.");
    }
  });

  document.getElementById("btn-delete")?.addEventListener("click", async () => {
    if (!window.confirm("Permanently delete this meeting and its audio?")) return;
    try {
      await apiRequest(`/api/v1/meetings/${meetingId}`, { method: "DELETE" });
      window.location.href = "/app";
    } catch (error) {
      showError(error.message || "Delete failed.");
    }
  });

  document.getElementById("ask-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("ask-input");
    const question = input.value.trim();
    if (!question) return;
    try {
      showError("");
      await askQuestion(question);
      input.value = "";
    } catch (error) {
      showError(error.message || "Could not answer question.");
    }
  });
}

init();
