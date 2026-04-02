import axios, { type InternalAxiosRequestConfig } from "axios";

/**
 * Axios instance with auth interceptors.
 *
 * - Request interceptor: attaches Bearer token from in-memory store
 * - Response interceptor: on 401, attempts one silent refresh then retries.
 *   If the refresh itself fails, forces logout.
 *
 * The access token is stored in module-level state (NEVER localStorage).
 */

let accessToken: string | null = null;
let logoutCallback: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function setLogoutCallback(cb: () => void): void {
  logoutCallback = cb;
}

const api = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
  withCredentials: true, // send httpOnly refresh cookie
});

// ── Request interceptor: attach Bearer token ────────────────────────────────

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

// ── Response interceptor: handle 401 with silent refresh ────────────────────

let isRefreshing = false;
let refreshSubscribers: Array<(token: string) => void> = [];

function onRefreshed(token: string): void {
  refreshSubscribers.forEach((cb) => cb(token));
  refreshSubscribers = [];
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };

    // Don't retry refresh endpoint itself
    if (
      error.response?.status !== 401 ||
      originalRequest._retry ||
      originalRequest.url === "/auth/refresh"
    ) {
      return Promise.reject(error);
    }

    if (isRefreshing) {
      // Queue this request until refresh completes
      return new Promise((resolve) => {
        refreshSubscribers.push((token: string) => {
          originalRequest.headers.Authorization = `Bearer ${token}`;
          resolve(api(originalRequest));
        });
      });
    }

    originalRequest._retry = true;
    isRefreshing = true;

    try {
      const response = await api.post("/auth/refresh");
      const newToken = response.data.data.access_token as string;
      setAccessToken(newToken);
      onRefreshed(newToken);
      originalRequest.headers.Authorization = `Bearer ${newToken}`;
      return api(originalRequest);
    } catch {
      setAccessToken(null);
      logoutCallback?.();
      return Promise.reject(error);
    } finally {
      isRefreshing = false;
    }
  },
);

export default api;
