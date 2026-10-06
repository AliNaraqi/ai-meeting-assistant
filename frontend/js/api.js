/** API fetch wrapper with bearer auth and normalized errors. */

const DEFAULT_TIMEOUT_MS = 15000;

export function getStoredToken() {
  return localStorage.getItem("ama_access_token");
}

export function setStoredToken(token) {
  localStorage.setItem("ama_access_token", token);
}

export function clearStoredToken() {
  localStorage.removeItem("ama_access_token");
  localStorage.removeItem("ama_user_email");
  localStorage.removeItem("ama_read_only");
}

export function isReadOnlySession() {
  return localStorage.getItem("ama_read_only") === "1";
}

export function setReadOnlySession(value) {
  localStorage.setItem("ama_read_only", value ? "1" : "0");
}

export function getStoredEmail() {
  return localStorage.getItem("ama_user_email");
}

export function setStoredEmail(email) {
  localStorage.setItem("ama_user_email", email);
}

export async function apiRequest(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs || DEFAULT_TIMEOUT_MS);
  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  const token = getStoredToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  try {
    const response = await fetch(path, {
      ...options,
      headers,
      signal: controller.signal,
    });
    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { raw: text };
      }
    }
    if (!response.ok) {
      const message =
        data?.error?.message || data?.detail?.error?.message || data?.detail || response.statusText;
      const error = new Error(typeof message === "string" ? message : "Request failed");
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  } finally {
    clearTimeout(timeout);
  }
}
