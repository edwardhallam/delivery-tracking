import { formatEventDate } from "@/utils/dates";
import type { DeliveryEvent } from "@/types/api";

interface EventLogProps {
  events: DeliveryEvent[];
}

export default function EventLog({ events }: EventLogProps) {
  if (events.length === 0) {
    return (
      <p className="py-4 text-sm text-text-muted">No tracking events yet.</p>
    );
  }

  // Highest sequence number first (most recent)
  const sorted = [...events].sort(
    (a, b) => b.sequence_number - a.sequence_number,
  );

  return (
    <ul className="divide-y divide-border">
      {sorted.map((evt) => (
        <li key={evt.id} className="py-3">
          <div className="flex items-start gap-3">
            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-text-muted" />
            <div className="min-w-0 flex-1">
              <p className="text-sm text-text">{evt.event_description}</p>
              {evt.location && (
                <p className="text-xs text-text-secondary">{evt.location}</p>
              )}
              {evt.additional_info && (
                <p className="mt-0.5 text-xs italic text-text-muted">
                  {evt.additional_info}
                </p>
              )}
              <p className="mt-0.5 text-xs text-text-muted">
                {formatEventDate(evt.event_date_raw)}
              </p>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
