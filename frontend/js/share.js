/** Public shared meeting page (no auth). */

import { initThemeToggle } from "./theme.js";
import { clearState, renderState, setText, showError } from "./ui.js";

const token = window.location.pathname.split("/").filter(Boolean).pop();

function formatMs(ms) {
  const total = Math.floor(ms / 1000);
  const m = String(Math.floor(total / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
}

async function init() {
  initThemeToggle();
  const errorEl = document.getElementById("page-error");
  const loading = document.getElementById("share-loading");
  renderState(loading, { variant: "loading", title: "Loading shared meeting…" });
  try {
    const response = await fetch(`/api/v1/share/${encodeURIComponent(token || "")}`);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(body?.error?.message || "Share link unavailable.");
    }
    clearState(loading);
    loading.hidden = true;

    setText(document.getElementById("share-title"), body.title || "Shared meeting");
    setText(
      document.getElementById("share-meta"),
      `${body.meeting_type || ""} · expires ${body.expires_at || ""}`.trim(),
    );

    if (body.insights) {
      const panel = document.getElementById("insights-panel");
      const summary = document.getElementById("insight-summary");
      const decisions = document.getElementById("insight-decisions");
      const actions = document.getElementById("insight-actions");
      panel.hidden = false;
      summary.replaceChildren();
      const one = document.createElement("p");
      one.textContent = body.insights.one_sentence_summary || "";
      const exec = document.createElement("p");
      exec.className = "meeting-meta";
      exec.textContent = body.insights.executive_summary || "";
      summary.append(one, exec);
      decisions.replaceChildren();
      for (const item of body.insights.decisions || []) {
        const li = document.createElement("li");
        li.className = "meeting-item";
        li.textContent = item.text || "";
        decisions.append(li);
      }
      actions.replaceChildren();
      for (const item of body.actions || []) {
        const li = document.createElement("li");
        li.className = "meeting-item";
        li.textContent = `[${item.status}] ${item.task}`;
        actions.append(li);
      }
    }

    if (body.transcript?.length) {
      const panel = document.getElementById("transcript-panel");
      const list = document.getElementById("transcript-list");
      panel.hidden = false;
      list.replaceChildren();
      for (const item of body.transcript) {
        const li = document.createElement("li");
        li.className = "meeting-item";
        const who = document.createElement("strong");
        who.textContent = `${item.speaker_label} · ${formatMs(item.start_ms)}`;
        const text = document.createElement("span");
        text.className = "meeting-meta";
        text.textContent = item.text;
        li.append(who, text);
        list.append(li);
      }
    } else if (!body.insights) {
      renderState(loading, {
        variant: "empty",
        title: "Nothing to show",
        body: "This share link has no transcript or insights attached.",
        actionHref: "/",
        actionLabel: "Back home",
      });
      loading.hidden = false;
    }
  } catch (error) {
    showError(errorEl, "");
    renderState(loading, {
      variant: "error",
      title: "Share link unavailable",
      body: error.message || "This link may have expired or been revoked.",
      actionHref: "/",
      actionLabel: "Back home",
    });
  }
}

init();
