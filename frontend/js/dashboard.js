/** Dashboard meeting list, process trigger, and transcript preview. */

import { apiRequest, getStoredEmail, isReadOnlySession } from "./api.js";
import { requireAuth, signOut } from "./auth.js";
import { initThemeToggle } from "./theme.js";
import { clearState, renderState, setText, showError } from "./ui.js";

const pollTimers = new Map();

function formatStatus(status) {
  return status.replaceAll("_", " ");
}

function formatMs(ms) {
  const total = Math.floor(ms / 1000);
  const m = String(Math.floor(total / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
}

async function processMeeting(meetingId, statusEl) {
  setText(statusEl, "Queueing…");
  const job = await apiRequest(`/api/v1/meetings/${meetingId}/process`, { method: "POST" });
  setText(statusEl, `${job.status} ${job.progress_percent || 0}%`);
  if (job.status === "queued" || job.status === "running") {
    startPolling(meetingId, statusEl);
  } else if (job.status === "succeeded") {
    await showTranscript(meetingId);
    await showInsights(meetingId);
  }
}

function startPolling(meetingId, statusEl) {
  if (pollTimers.has(meetingId)) return;
  const timer = setInterval(async () => {
    try {
      const job = await apiRequest(`/api/v1/meetings/${meetingId}/jobs/latest`);
      setText(
        statusEl,
        `${job.status}${job.stage ? ` · ${job.stage}` : ""} · ${job.progress_percent}%`,
      );
      if (job.status === "succeeded") {
        clearInterval(timer);
        pollTimers.delete(meetingId);
        await loadMeetings();
        await showTranscript(meetingId);
        await showInsights(meetingId);
      } else if (job.status === "failed" || job.status === "cancelled") {
        clearInterval(timer);
        pollTimers.delete(meetingId);
        setText(statusEl, job.safe_error?.message || job.status);
      }
    } catch (error) {
      clearInterval(timer);
      pollTimers.delete(meetingId);
      setText(statusEl, error.message || "Polling failed");
    }
  }, 1500);
  pollTimers.set(meetingId, timer);
}

async function showTranscript(meetingId) {
  const panel = document.getElementById("transcript-panel");
  const list = document.getElementById("transcript-list");
  if (!panel || !list) return;
  const data = await apiRequest(`/api/v1/meetings/${meetingId}/transcript`);
  list.replaceChildren();
  for (const item of data.items || []) {
    const li = document.createElement("li");
    li.className = "meeting-item";
    const who = document.createElement("strong");
    who.textContent = `${item.speaker.label} · ${formatMs(item.start_ms)}`;
    const text = document.createElement("span");
    text.className = "meeting-meta";
    text.textContent = item.text;
    li.append(who, text);
    list.append(li);
  }
  panel.hidden = false;
}

async function showInsights(meetingId) {
  const panel = document.getElementById("insights-panel");
  const summaryEl = document.getElementById("insight-summary");
  const decisionsEl = document.getElementById("insight-decisions");
  const actionsEl = document.getElementById("insight-actions");
  if (!panel || !summaryEl || !decisionsEl || !actionsEl) return;

  const [insights, actions] = await Promise.all([
    apiRequest(`/api/v1/meetings/${meetingId}/insights`),
    apiRequest(`/api/v1/meetings/${meetingId}/actions`),
  ]);

  summaryEl.replaceChildren();
  const one = document.createElement("p");
  one.textContent = insights.one_sentence_summary;
  const exec = document.createElement("p");
  exec.className = "meeting-meta";
  exec.textContent = insights.executive_summary;
  const editBtn = document.createElement("button");
  editBtn.type = "button";
  editBtn.className = "button-quiet";
  editBtn.textContent = "Edit summary";
  editBtn.addEventListener("click", async () => {
    const next = window.prompt("One-sentence summary", insights.one_sentence_summary);
    if (!next) return;
    await apiRequest(`/api/v1/meetings/${meetingId}/insights`, {
      method: "PATCH",
      body: JSON.stringify({ one_sentence_summary: next }),
    });
    await showInsights(meetingId);
  });
  summaryEl.append(one, exec, editBtn);

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
    const label = document.createElement("strong");
    label.textContent = action.task;
    const meta = document.createElement("span");
    meta.className = "meeting-meta";
    meta.textContent = `${action.status} · confidence ${action.confidence_label}`;
    const complete = document.createElement("button");
    complete.type = "button";
    complete.className = "button-quiet";
    complete.textContent = action.status === "completed" ? "Reopen" : "Complete";
    complete.addEventListener("click", async () => {
      await apiRequest(`/api/v1/meetings/${meetingId}/actions/${action.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: action.status === "completed" ? "open" : "completed",
        }),
      });
      await showInsights(meetingId);
    });
    li.append(label, meta, complete);
    actionsEl.append(li);
  }
  if (!(actions || []).length) {
    const li = document.createElement("li");
    li.className = "meeting-meta";
    li.textContent = "No action items captured.";
    actionsEl.append(li);
  }

  panel.hidden = false;
}

function renderMeetings(items) {
  const list = document.getElementById("meeting-list");
  const empty = document.getElementById("empty-state");
  if (!list || !empty) return;

  list.replaceChildren();
  if (!items.length) {
    empty.hidden = false;
    renderState(empty, {
      variant: "empty",
      title: "No meetings yet",
      body: "Create a meeting, upload audio, and process it to see transcripts and insights here.",
      actionHref: "/meetings/new",
      actionLabel: "New meeting",
    });
    return;
  }
  empty.hidden = true;
  clearState(empty);
  for (const meeting of items) {
    const li = document.createElement("li");
    li.className = "meeting-item";

    const title = document.createElement("strong");
    title.textContent = meeting.title;

    const meta = document.createElement("span");
    meta.className = "meeting-meta";
    meta.textContent = `${formatStatus(meeting.status)} · ${meeting.meeting_type} · ${new Date(
      meeting.created_at,
    ).toLocaleString()}`;

    const actions = document.createElement("div");
    actions.className = "button-row";
    const statusEl = document.createElement("span");
    statusEl.className = "meeting-meta";
    statusEl.id = `job-status-${meeting.id}`;

    if (["uploaded", "failed", "ready"].includes(meeting.status)) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "button-primary";
      btn.textContent = meeting.status === "ready" ? "Re-process" : "Process";
      btn.addEventListener("click", async () => {
        try {
          await processMeeting(meeting.id, statusEl);
          await loadMeetings();
        } catch (error) {
          setText(statusEl, error.message || "Process failed");
        }
      });
      actions.append(btn);
    }

    const open = document.createElement("a");
    open.href = `/meetings/${meeting.id}`;
    open.className = "button-quiet";
    open.textContent = "Open workspace";
    actions.append(open);

    if (meeting.status === "ready") {
      const view = document.createElement("button");
      view.type = "button";
      view.className = "button-quiet";
      view.textContent = "Quick transcript";
      view.addEventListener("click", () => showTranscript(meeting.id));
      actions.append(view);

      const overview = document.createElement("button");
      overview.type = "button";
      overview.className = "button-quiet";
      overview.textContent = "Quick overview";
      overview.addEventListener("click", () => showInsights(meeting.id));
      actions.append(overview);
    }

    if (["queued", "processing"].includes(meeting.status)) {
      startPolling(meeting.id, statusEl);
    }

    actions.append(statusEl);
    li.append(title, meta, actions);
    list.append(li);
  }
}

async function loadMeetings() {
  const errorEl = document.getElementById("dashboard-error");
  const empty = document.getElementById("empty-state");
  const list = document.getElementById("meeting-list");
  showError(errorEl, "");
  if (empty) {
    empty.hidden = false;
    renderState(empty, { variant: "loading", title: "Loading meetings…" });
  }
  if (list) list.replaceChildren();
  try {
    const data = await apiRequest("/api/v1/meetings");
    renderMeetings(data.items || []);
  } catch (error) {
    if (empty) {
      renderState(empty, {
        variant: "error",
        title: "Could not load meetings",
        body: error.message || "Check your connection and try again.",
        actionLabel: "Retry",
        onAction: () => void loadMeetings(),
      });
    }
    showError(errorEl, error.message || "Could not load meetings.");
  }
}

async function loadUsage() {
  const chip = document.getElementById("usage-chip");
  if (!chip) return;
  try {
    const usage = await apiRequest("/api/v1/me/usage");
    chip.hidden = false;
    chip.textContent = `${usage.audio_minutes_remaining} min · ${Number(
      usage.llm_tokens_remaining,
    ).toLocaleString()} tokens left`;
  } catch {
    chip.hidden = true;
  }
}

function init() {
  if (!requireAuth()) return;
  initThemeToggle();
  const email = getStoredEmail();
  const readOnly = isReadOnlySession();
  setText(
    document.getElementById("user-email"),
    readOnly ? `${email || "Demo"} · read-only` : email || "Signed in",
  );
  document.getElementById("sign-out")?.addEventListener("click", signOut);
  if (readOnly) {
    const newLink = document.querySelector('a[href="/meetings/new"]');
    if (newLink) {
      newLink.textContent = "Sign in to create";
      newLink.href = "/login";
    }
  }
  void loadUsage();
  loadMeetings();
}

init();
