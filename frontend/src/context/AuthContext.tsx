import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import api, { setAccessToken, setLogoutCallback } from "@/api/client";

interface AuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (token: string) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const login = useCallback((newToken: string) => {
    setToken(newToken);
    setAccessToken(newToken);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      // Logout endpoint may fail if token already expired — that's fine
    }
    setToken(null);
    setAccessToken(null);
  }, []);

  // Register logout callback for the interceptor
  useEffect(() => {
    setLogoutCallback(() => {
      setToken(null);
      setAccessToken(null);
    });
  }, []);

  // Silent refresh on app load — no login flash
  useEffect(() => {
    let cancelled = false;

    async function silentRefresh() {
      try {
        const response = await api.post("/auth/refresh");
        if (!cancelled) {
          const newToken = response.data.data.access_token as string;
          setToken(newToken);
          setAccessToken(newToken);
        }
      } catch {
        // No valid refresh cookie — user needs to log in
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void silentRefresh();
    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      isAuthenticated: token !== null,
      isLoading,
      login,
      logout,
    }),
    [token, isLoading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
