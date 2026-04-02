/**
 * Expected date display logic per requirements:
 * - timestamp_expected present -> relative label (Today, Tomorrow, day name, short date)
 * - date_expected_raw only -> verbatim with ~ prefix
 * - Neither -> em dash
 */

const DAY_NAMES = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
] as const;

function startOfDay(d: Date): Date {
  const copy = new Date(d);
  copy.setHours(0, 0, 0, 0);
  return copy;
}

function daysBetween(a: Date, b: Date): number {
  const msPerDay = 86_400_000;
  return Math.round(
    (startOfDay(b).getTime() - startOfDay(a).getTime()) / msPerDay,
  );
}

export function formatExpectedDate(
  timestampExpected: string | null,
  dateExpectedRaw: string | null,
): string {
  if (timestampExpected) {
    const date = new Date(timestampExpected);
    if (isNaN(date.getTime())) return timestampExpected;

    const now = new Date();
    const diff = daysBetween(now, date);

    if (diff === 0) return "Today";
    if (diff === 1) return "Tomorrow";
    if (diff === -1) return "Yesterday";

    // Within the next 6 days: show day name
    if (diff > 1 && diff <= 6) {
      return DAY_NAMES[date.getDay()]!;
    }

    // Otherwise show short date
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year:
        date.getFullYear() !== now.getFullYear() ? "numeric" : undefined,
    });
  }

  if (dateExpectedRaw) {
    return `~${dateExpectedRaw}`;
  }

  return "\u2014"; // em dash
}

/**
 * Format an ISO timestamp into a human-readable relative or absolute string.
 */
export function formatRelativeTime(iso: string): string {
  const date = new Date(iso);
  if (isNaN(date.getTime())) return iso;

  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60_000);

  if (diffMin < 1) return "Just now";
  if (diffMin < 60) return `${diffMin} min ago`;

  const diffHours = Math.floor(diffMin / 60);
  if (diffHours < 24) return `${diffHours}h ago`;

  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * Format an ISO timestamp for event display.
 */
export function formatEventDate(iso: string): string {
  const date = new Date(iso);
  if (isNaN(date.getTime())) return iso;

  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
