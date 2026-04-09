import { formatEventDate } from "@/utils/dates";
import type { StatusHistoryEntry, SemanticStatus } from "@/types/api";

const STATUS_LABELS: Record<SemanticStatus, string> = {
  INFO_RECEIVED: "Info Received",
  IN_TRANSIT: "In Transit",
  OUT_FOR_DELIVERY: "Out for Delivery",
  AWAITING_PICKUP: "Awaiting Pickup",
  DELIVERED: "Delivered",
  DELIVERY_FAILED: "Delivery Failed",
  EXCEPTION: "Exception",
  NOT_FOUND: "Not Found",
  FROZEN: "Frozen",
  UNKNOWN: "Unknown",
};

interface TimelineProps {
  history: StatusHistoryEntry[];
}

export default function Timeline({ history }: TimelineProps) {
  if (history.length === 0) {
    return (
      <p className="py-4 text-sm text-text-muted">No status history yet.</p>
    );
  }

  // Most recent first
  const sorted = [...history].sort(
    (a, b) => new Date(b.detected_at).getTime() - new Date(a.detected_at).getTime(),
  );

  return (
    <div className="relative pl-6">
      {/* Vertical line */}
      <div className="absolute left-[9px] top-2 bottom-2 w-px bg-border" />

      <ul className="space-y-4">
        {sorted.map((entry, i) => {
          const isCurrent = i === 0;
          return (
            <li key={entry.id} className="relative">
              {/* Dot */}
              <span
                className={`absolute -left-6 top-1 h-[18px] w-[18px] rounded-full border-2 ${
                  isCurrent
                    ? "border-primary bg-primary"
                    : "border-border bg-card"
                }`}
              />
              <div>
                <p
                  className={`text-sm font-medium ${
                    isCurrent ? "text-primary" : "text-text"
                  }`}
                >
                  {STATUS_LABELS[entry.new_semantic_status] ??
                    entry.new_status_code}
                </p>
                {entry.previous_semantic_status && (
                  <p className="text-xs text-text-muted">
                    from{" "}
                    {STATUS_LABELS[entry.previous_semantic_status] ??
                      entry.previous_status_code}
                  </p>
                )}
                <p className="mt-0.5 text-xs text-text-secondary">
                  {formatEventDate(entry.detected_at)}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
