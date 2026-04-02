import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { Package, Loader2, AlertCircle } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import api from "@/api/client";
import type { ApiResponse, AuthTokenResponse } from "@/types/api";
import { AxiosError } from "axios";

export default function LoginPage() {
  const { isAuthenticated, isLoading, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Already logged in — redirect
  if (isAuthenticated && !isLoading) {
    return <Navigate to="/deliveries" replace />;
  }

  // Still checking silent refresh
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-bg">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const response = await api.post<ApiResponse<AuthTokenResponse>>(
        "/auth/login",
        { username, password },
      );
      login(response.data.data.access_token);
    } catch (err) {
      if (err instanceof AxiosError && err.response?.data?.error?.message) {
        setError(err.response.data.error.message as string);
      } else {
        setError("Unable to sign in. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-4">
      <div className="w-full max-w-sm">
        <div className="rounded-xl border border-border bg-card p-8 shadow-sm">
          {/* Header */}
          <div className="mb-6 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-active-blue-bg">
              <Package className="h-6 w-6 text-primary" />
            </div>
            <h1 className="font-heading text-2xl font-semibold text-text">
              Delivery Tracker
            </h1>
            <p className="mt-1 text-sm text-text-secondary">
              Sign in to your account
            </p>
          </div>

          {/* Error */}
          {error && (
            <div className="mb-4 flex items-start gap-2 rounded-lg bg-danger-bg-light p-3">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          {/* Form */}
          <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
            <div>
              <label
                htmlFor="username"
                className="mb-1 block text-sm font-medium text-text"
              >
                Username
              </label>
              <input
                id="username"
                type="text"
                required
                autoComplete="username"
                autoFocus
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full rounded-lg border border-input-border bg-card px-3 py-2 text-sm text-text placeholder:text-text-muted outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/20"
                placeholder="Enter your username"
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="mb-1 block text-sm font-medium text-text"
              >
                Password
              </label>
              <input
                id="password"
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-lg border border-input-border bg-card px-3 py-2 text-sm text-text placeholder:text-text-muted outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/20"
                placeholder="Enter your password"
              />
            </div>

            <button
              type="submit"
              disabled={submitting || !username || !password}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 font-heading text-sm font-semibold text-white transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
              Sign In
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
