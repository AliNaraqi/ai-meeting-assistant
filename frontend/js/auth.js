/** Dev-mode authentication helpers. */

import {
  apiRequest,
  clearStoredToken,
  getStoredToken,
  setStoredEmail,
  setStoredToken,
} from "./api.js";

export async function devLogin(email, displayName) {
  const data = await apiRequest("/api/v1/auth/dev-login", {
    method: "POST",
    body: JSON.stringify({
      email,
      display_name: displayName || null,
    }),
  });
  setStoredToken(data.access_token);
  setStoredEmail(data.email);
  localStorage.setItem("ama_read_only", email.toLowerCase() === "demo@example.com" ? "1" : "0");
  return data;
}

export function requireAuth() {
  if (!getStoredToken()) {
    window.location.href = "/login";
    return false;
  }
  return true;
}

export function signOut() {
  clearStoredToken();
  window.location.href = "/login";
}
