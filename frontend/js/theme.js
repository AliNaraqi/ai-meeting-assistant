/** Theme preference: system / light / dark with nav toggle. */

const STORAGE_KEY = "ama_theme";

export function getPreferredTheme() {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function getStoredTheme() {
  return localStorage.getItem(STORAGE_KEY);
}

export function applyTheme(theme) {
  if (theme === "light" || theme === "dark") {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(STORAGE_KEY, theme);
  } else {
    delete document.documentElement.dataset.theme;
    localStorage.removeItem(STORAGE_KEY);
  }
  syncToggleLabel();
}

function syncToggleLabel() {
  const button = document.getElementById("theme-toggle");
  if (!button) return;
  const effective = getPreferredTheme();
  const next = effective === "dark" ? "light" : "dark";
  button.textContent = effective === "dark" ? "Light" : "Dark";
  button.setAttribute("aria-label", `Switch to ${next} mode`);
  button.title = `Theme: ${effective} (click for ${next})`;
}

export function toggleTheme() {
  const next = getPreferredTheme() === "dark" ? "light" : "dark";
  applyTheme(next);
}

export function initThemeToggle() {
  let button = document.getElementById("theme-toggle");
  if (!button) {
    const nav = document.querySelector(".site-nav");
    if (!nav) return;
    button = document.createElement("button");
    button.type = "button";
    button.id = "theme-toggle";
    button.className = "button-quiet";
    nav.append(button);
  }
  button.addEventListener("click", () => toggleTheme());
  syncToggleLabel();

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (!getStoredTheme()) syncToggleLabel();
  });
}
