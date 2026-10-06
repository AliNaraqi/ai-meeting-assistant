/** Landing page: open the shared read-only demo meeting without signup. */

import { apiRequest, setStoredEmail, setStoredToken } from "./api.js";
import { initThemeToggle } from "./theme.js";
import { setText } from "./ui.js";

initThemeToggle();

function setDemoStatus(message) {
  const el = document.getElementById("demo-status");
  if (!el) return;
  setText(el, message || "");
  el.hidden = !message;
}

async function viewDemoMeeting() {
  const button = document.getElementById("view-demo");
  if (button) button.disabled = true;
  setDemoStatus("Opening demo…");
  try {
    const data = await apiRequest("/api/v1/auth/demo-login", { method: "POST" });
    setStoredToken(data.access_token);
    setStoredEmail(data.email);
    localStorage.setItem("ama_read_only", data.read_only ? "1" : "0");
    window.location.href = `/meetings/${data.meeting_id}`;
  } catch (error) {
    setDemoStatus(error.message || "Demo is unavailable right now.");
    if (button) button.disabled = false;
  }
}

document.getElementById("view-demo")?.addEventListener("click", () => {
  void viewDemoMeeting();
});
