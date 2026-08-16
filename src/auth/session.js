const CORE_API = import.meta.env.VITE_SPPG_CORE_API_URL || "https://sppg-finance-gpt-site-production-5b7d.up.railway.app";

const TOKEN_KEY = "sppg_session_token_v1";
const ROLE_KEY = "sppg_session_role_v1";

export function readSessionToken() {
  return sessionStorage.getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY) || "";
}

export function readSessionRole() {
  return sessionStorage.getItem(ROLE_KEY) || localStorage.getItem(ROLE_KEY) || "";
}

export function storeSession({ token, role, remember }) {
  clearSession();
  const storage = remember ? localStorage : sessionStorage;
  storage.setItem(TOKEN_KEY, token);
  storage.setItem(ROLE_KEY, role);
}

export function clearSession() {
  for (const storage of [sessionStorage, localStorage]) {
    storage.removeItem(TOKEN_KEY);
    storage.removeItem(ROLE_KEY);
  }
}

async function api(path, options = {}) {
  const response = await fetch(`${CORE_API}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  let payload = null;
  try { payload = await response.json(); } catch {}
  if (!response.ok) {
    const message = payload?.detail || payload?.message || response.statusText || "Permintaan gagal";
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return payload;
}

export const authApi = {
  config: () => api("/v1/auth/config"),
  login: ({ username, password, remember }) => api("/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password, remember }),
  }),
  me: (token = readSessionToken()) => api("/v1/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
  }),
  firebaseCemplangToken: (token = readSessionToken()) => api("/v1/auth/firebase-token/cemplang", {
    headers: { Authorization: `Bearer ${token}` },
  }),
  logout: () => api("/v1/auth/logout", { method: "POST" }).catch(() => null),
};

export { CORE_API, TOKEN_KEY, ROLE_KEY };
