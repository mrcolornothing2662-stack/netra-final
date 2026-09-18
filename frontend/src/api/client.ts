/**
 * CyberDrishti AI — Native API Client
 * Zero-dependency fetch-based client with explicit JWT bearer handling.
 *
 * Authentication is explicit: the user signs in via the login screen, which
 * calls login() below. There is NO hardcoded credential and NO silent
 * auto-login. When a token is missing or rejected, the app routes the user to
 * the login screen rather than fabricating a session or falling back to a
 * demo identity.
 */

const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, "") ||
  (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/+$/, "") ||
  "/api/v1";
const TOKEN_KEY = "cd_token";
const USER_KEY = "cd_user";
const LOGIN_PATH = "/login";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  if (typeof window !== "undefined") {
    localStorage.setItem(TOKEN_KEY, token);
  }
}

export function clearToken() {
  if (typeof window !== "undefined") {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }
}

export interface UserSession {
  id: string;
  username: string;
  role: string;
  full_name?: string | null;
  email?: string | null;
  rank?: string | null;
  unit?: string | null;
  must_change_password?: boolean;
}

export function getStoredUser(): UserSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setStoredUser(user: UserSession) {
  if (typeof window !== "undefined") {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  }
}

export function isTokenExpired(token: string): boolean {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return true;
    const payload = JSON.parse(atob(parts[1]));
    if (!payload.exp) return false;
    return Date.now() >= payload.exp * 1000 - 30000; // 30s grace window
  } catch {
    return true;
  }
}

/** True when a non-expired token is present. Used by the route guard. */
export function isAuthenticated(): boolean {
  const t = getToken();
  return !!t && !isTokenExpired(t);
}

export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(message: string, status: number, data?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

function redirectToLogin() {
  if (typeof window === "undefined") return;
  if (!window.location.pathname.startsWith(LOGIN_PATH) && window.location.pathname !== "/") {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.assign(`${LOGIN_PATH}?next=${next}`);
  }
}

/**
 * Explicit sign-in. Posts the credential form to /auth/login, stores the JWT,
 * then loads the real identity from /auth/me. Throws ApiError on failure — the
 * login screen surfaces the message; nothing is fabricated.
 */
export async function login(username: string, password: string): Promise<UserSession> {
  const params = new URLSearchParams({ username, password });
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: params.toString(),
    });
  } catch {
    throw new ApiError("Unable to reach the authentication server.", 0);
  }

  if (!res.ok) {
    let detail = "Incorrect username or password.";
    try {
      const d = await res.json();
      if (d && typeof d === "object" && "detail" in d) detail = String((d as { detail: unknown }).detail);
    } catch {
      /* non-json */
    }
    throw new ApiError(detail, res.status);
  }

  const data = await res.json();
  if (!data?.access_token) {
    throw new ApiError("Login failed: no token was issued.", 500);
  }
  setToken(data.access_token);

  let user: UserSession;
  try {
    user = await fetchMe();
  } catch {
    // Token is valid but /me failed — record what the token told us, no more.
    user = {
      id: "",
      username,
      role: data.role || "io",
      full_name: data.full_name ?? null,
      must_change_password: !!data.must_change_password,
    };
  }
  setStoredUser(user);
  return user;
}

/** Load the authenticated user's real identity from the backend. */
export async function fetchMe(): Promise<UserSession> {
  const token = getToken();
  if (!token) throw new ApiError("Not authenticated", 401);
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new ApiError("Failed to load identity", res.status);
  const u = await res.json();
  const user: UserSession = {
    id: u.id,
    username: u.username,
    role: u.role,
    full_name: u.full_name ?? null,
    email: u.email ?? null,
    rank: u.rank ?? null,
    unit: u.unit ?? null,
    must_change_password: !!u.must_change_password,
  };
  setStoredUser(user);
  return user;
}

/** Change the current authenticated user's password. */
export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const token = getToken();
  if (!token) throw new ApiError("Not authenticated", 401);
  const res = await fetch(`${API_BASE}/auth/change-password`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
  if (!res.ok) {
    let detail = "Failed to change password.";
    try {
      const d = await res.json();
      if (d && typeof d === "object" && "detail" in d) {
        detail = String((d as { detail: unknown }).detail);
      }
    } catch {}
    throw new ApiError(detail, res.status);
  }
  const current = getStoredUser();
  if (current) {
    current.must_change_password = false;
    setStoredUser(current);
  }
}

/** Sign out: clear the session and return to the login screen. */
export function logout() {
  clearToken();
  if (typeof window !== "undefined") {
    window.location.assign(LOGIN_PATH);
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();

  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  if (token && !headers["Authorization"]) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const url = endpoint.startsWith("http") ? endpoint : `${API_BASE}${endpoint.startsWith("/") ? "" : "/"}${endpoint}`;

  const controller = new AbortController();
  // Must exceed the backend's longest upstream wait (Ollama generate ≈ 25s in
  // rag/copilot.py) so a slow-but-valid AI response is not aborted here and
  // surfaced as a false failure. Callers may pass their own signal to override.
  const REQUEST_TIMEOUT_MS = 30000;
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const signal = options.signal || controller.signal;

  let res: Response;
  try {
    res = await fetch(url, { ...options, headers, signal });
  } finally {
    clearTimeout(timeoutId);
  }

  // No silent re-authentication. A rejected token means the session is over —
  // clear it and route the user back to the login screen.
  if (res.status === 401) {
    clearToken();
    redirectToLogin();
    throw new ApiError("Session expired. Please sign in again.", 401);
  }

  if (!res.ok) {
    let backendDetail: string | null = null;
    let errorData: unknown = null;
    try {
      errorData = await res.json();
      if (typeof errorData === "object" && errorData !== null && "detail" in errorData) {
        backendDetail = String((errorData as { detail: unknown }).detail);
      }
    } catch {
      // response was not json
    }

    // Never surface a raw server exception (e.g. "… status 500") to the
    // investigator. Map the status to an honest, actionable message and keep
    // the technical detail on the error object for diagnostics.
    let message: string;
    if (res.status >= 500) {
      message = "The service could not complete the request. Please retry.";
    } else if (res.status === 403) {
      message = "You do not have access to this resource.";
    } else if (res.status === 404) {
      message = backendDetail && backendDetail.toLowerCase() !== "not found"
        ? backendDetail
        : "The requested case or resource was not found.";
    } else {
      message = backendDetail || `Request failed (status ${res.status}).`;
    }
    throw new ApiError(message, res.status, errorData);
  }

  const contentType = res.headers.get("content-type");
  if (contentType && contentType.includes("application/json")) {
    return res.json() as Promise<T>;
  }

  return res.text() as unknown as Promise<T>;
}

export const apiClient = {
  get: <T>(endpoint: string, headers?: Record<string, string>) =>
    request<T>(endpoint, { method: "GET", headers }),

  post: <T>(endpoint: string, body?: unknown, headers?: Record<string, string>) =>
    request<T>(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),

  patch: <T>(endpoint: string, body?: unknown, headers?: Record<string, string>) =>
    request<T>(endpoint, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...headers },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),

  delete: <T>(endpoint: string, headers?: Record<string, string>) =>
    request<T>(endpoint, { method: "DELETE", headers }),

  postForm: <T>(endpoint: string, formData: FormData) =>
    request<T>(endpoint, {
      method: "POST",
      body: formData,
    }),

  getBlob: async (endpoint: string): Promise<Blob> => {
    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const url = endpoint.startsWith("http") ? endpoint : `${API_BASE}${endpoint.startsWith("/") ? "" : "/"}${endpoint}`;
    const res = await fetch(url, { headers });
    if (res.status === 401) {
      clearToken();
      redirectToLogin();
      throw new ApiError("Session expired. Please sign in again.", 401);
    }
    if (!res.ok) {
      throw new ApiError(`Download failed (${res.status})`, res.status);
    }
    return res.blob();
  },
};
