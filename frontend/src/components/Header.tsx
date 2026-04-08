import { Package, RefreshCw, LogOut } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useHealth } from "@/hooks/useHealth";
import { useMe } from "@/hooks/useMe";
import { formatRelativeTime } from "@/utils/dates";

function DemoBanner() {
  return (
    <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 text-center text-sm text-amber-800">
      Demo Mode — APIs are not active.
    </div>
  );
}

function PollIndicator() {
  const { data: health } = useHealth();

  if (!health) {
    return (
      <span className="flex items-center gap-1.5 text-xs text-text-muted">
        <span className="h-2 w-2 rounded-full bg-text-muted" />
        Checking...
      </span>
    );
  }

  const { polling } = health;
  const isRunning = polling.scheduler_running;
  const hasErrors = polling.consecutive_errors > 0;

  let dotColor = "bg-text-muted"; // grey: unknown
  let label = "Poll status unknown";

  if (isRunning && !hasErrors && polling.last_successful_poll_at) {
    dotColor = "bg-poll-green";
    label = `Last polled ${formatRelativeTime(polling.last_successful_poll_at)}`;
  } else if (isRunning && hasErrors) {
    dotColor = "bg-amber-500";
    label = `Poll errors: ${polling.consecutive_errors}`;
  } else if (!isRunning) {
    dotColor = "bg-danger";
    label = "Polling stopped";
  }

  return (
    <span className="flex items-center gap-1.5 text-xs text-text-secondary">
      <span className={`h-2 w-2 rounded-full ${dotColor}`} />
      {label}
    </span>
  );
}

export default function Header() {
  const { logout } = useAuth();
  const { refetch: refetchHealth } = useHealth();
  const { data: me } = useMe();
  const isDemo = me?.is_demo ?? false;

  return (
    <>
      {isDemo && <DemoBanner />}
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6">
          {/* Left: logo + title */}
          <div className="flex items-center gap-2">
            <Package className="h-5 w-5 text-primary" />
            <span className="font-heading text-lg font-semibold text-text">
              Delivery Tracker
            </span>
          </div>

          {/* Right: poll status + actions */}
          <div className="flex items-center gap-3">
            {!isDemo && <PollIndicator />}

            {!isDemo && (
              <button
                onClick={() => void refetchHealth()}
                className="flex items-center gap-1.5 rounded-md border border-border bg-secondary-bg px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:bg-border transition-colors"
                title="Refresh health"
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            )}

            <button
              onClick={() => void logout()}
              className="flex items-center gap-1.5 rounded-md border border-border bg-secondary-bg px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:bg-border transition-colors"
            >
              <LogOut className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Logout</span>
            </button>
          </div>
        </div>
      </header>
    </>
  );
}
