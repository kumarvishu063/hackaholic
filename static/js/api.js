/**
 * JanSetu API client.
 *
 * - Attaches the JWT access token to every request.
 * - Automatically refreshes the token pair once when a 401 is received.
 * - Normalises errors into readable messages.
 */
const Api = (() => {
  const BASE = "/api";
  const TOKENS_KEY = "jst_tokens";
  const USER_KEY = "jst_user";

  // ------------------------------------------------------------------ storage
  function getTokens() {
    try { return JSON.parse(localStorage.getItem(TOKENS_KEY) || "null"); } catch { return null; }
  }
  function setTokens(tokens) {
    localStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));
  }
  function getUser() {
    try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); } catch { return null; }
  }
  function setUser(user) { localStorage.setItem(USER_KEY, JSON.stringify(user)); }
  function clearSession() {
    localStorage.removeItem(TOKENS_KEY);
    localStorage.removeItem(USER_KEY);
  }

  // ------------------------------------------------------------------ requests
  async function rawRequest(method, path, body, isForm, attempted = false) {
    const tokens = getTokens();
    const headers = {};
    if (body && !isForm) headers["Content-Type"] = "application/json";
    if (tokens && tokens.access_token) headers["Authorization"] = "Bearer " + tokens.access_token;

    const opts = { method, headers };
    if (body) opts.body = isForm ? body : JSON.stringify(body);

    const res = await fetch(BASE + path, opts);

    // Refresh the token pair at most ONCE per logical request, then give up.
    if (res.status === 401 && tokens && tokens.refresh_token && !attempted && !path.startsWith("/auth/")) {
      const refreshed = await tryRefresh(tokens.refresh_token);
      if (refreshed) return rawRequest(method, path, body, isForm, true); // retry once
      clearSession();
      if (!window.location.pathname.startsWith("/login")) {
        window.location.href = "/login/";
      }
    }
    return res;
  }

  async function tryRefresh(refreshToken) {
    try {
      const res = await fetch(BASE + "/auth/refresh/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      setTokens({ access_token: data.access_token, refresh_token: data.refresh_token });
      return true;
    } catch { return false; }
  }

  function extractError(data, status) {
    if (!data) return status >= 500 ? "Server error. Please try again." : "Something went wrong.";
    if (typeof data === "string") return data;
    if (data.detail) return data.detail;
    if (data.error) return data.error;
    for (const key of Object.keys(data)) {           // DRF field errors
      const val = data[key];
      if (Array.isArray(val) && val.length) return Array.isArray(val[0]) ? String(val[0][0]) : String(val[0]);
      if (typeof val === "string") return val;
    }
    return "Request failed.";
  }

  async function request(method, path, body, isForm = false) {
    const res = await rawRequest(method, path, body, isForm);
    let data = null;
    try { data = await res.json(); } catch { data = null; }
    if (!res.ok) {
      throw Object.assign(new Error(extractError(data, res.status)), { status: res.status, data });
    }
    return data;
  }

  /**
   * Post with an explicit bearer token (used to re-register a face with the
   * short-lived face-challenge token before a real access token exists).
   */
  async function postWithToken(path, body, token, isForm = false) {
    const headers = {};
    if (body && !isForm) headers["Content-Type"] = "application/json";
    if (token) headers["Authorization"] = "Bearer " + token;
    const opts = { method: "POST", headers };
    opts.body = isForm ? body : JSON.stringify(body);
    const res = await fetch(BASE + path, opts);
    let data = null;
    try { data = await res.json(); } catch { data = null; }
    if (!res.ok) {
      throw Object.assign(new Error(extractError(data, res.status)), { status: res.status, data });
    }
    return data;
  }

  /** Persist an authenticated payload (tokens + user) into local storage. */
  function saveSession(data) {
    if (data && data.access_token && data.refresh_token) {
      setTokens({ access_token: data.access_token, refresh_token: data.refresh_token });
    }
    if (data && data.user) setUser(data.user);
    return data && data.user ? data.user : (data.user || null);
  }

  // ------------------------------------------------------------------ public
  return {
    get: (path) => request("GET", path),
    post: (path, body, isForm) => request("POST", path, body, isForm),
    put: (path, body) => request("PUT", path, body),
    patch: (path, body) => request("PATCH", path, body),

    // Login returns the raw response — the caller decides whether it is a
    // complete session (citizen / super admin) or a face challenge (staff).
    login: async (identifier, password) =>
      request("POST", "/auth/login/", { identifier, password }),

    // Register returns the raw response — citizen registrations include
    // tokens, validator/official applications return a pending notice instead.
    register: async (payload, isForm) => request("POST", "/auth/register/", payload, isForm),

    verifyFace: (payload) => request("POST", "/auth/verify-face/", payload),
    registerFace: (payload, token) => postWithToken("/auth/register-face/", payload, token),
    registerFaceForm: (formData, token) => postWithToken("/auth/register-face/", formData, token, true),

    saveSession,
    logout: clearSession,
    getUser,
    setUser,
    getTokens,
    clearSession,
  };
})();
