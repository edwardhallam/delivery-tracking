import { AlertTriangle, Check } from "lucide-react";
import type { LifecycleGroup, SemanticStatus } from "@/types/api";

const STATUS_DISPLAY: Record<SemanticStatus, string> = {
  INFO_RECEIVED: "Info Received",
  IN_TRANSIT: "In Transit",
  OUT_FOR_DELIVERY: "Out for Delivery",
  AWAITING_PICKUP: "Awaiting Pickup",
  DELIVERED: "Delivered",
  DELIVERY_FAILED: "Delivery Failed",
  EXCEPTION: "Exception",
  NOT_FOUND: "Not Found",
  STALLED: "Stalled",
  UNKNOWN: "Unknown",
};

interface StatusBadgeProps {
  semanticStatus: SemanticStatus;
  lifecycleGroup: LifecycleGroup;
}

export default function StatusBadge({
  semanticStatus,
  lifecycleGroup,
}: StatusBadgeProps) {
  const label = STATUS_DISPLAY[semanticStatus] ?? semanticStatus;

  const styles = {
    ACTIVE: {
      bg: "bg-active-blue-bg",
      text: "text-active-blue",
      dot: "bg-active-blue",
    },
    ATTENTION: {
      bg: "bg-danger-bg-light",
      text: "text-danger",
      dot: null, // uses icon instead
    },
    TERMINAL: {
      bg: "bg-success-bg",
      text: "text-success",
      dot: null, // uses icon instead
    },
  } as const;

  // Frozen / stalled fall under TERMINAL group but should look grey
  const isFrozen =
    semanticStatus === "STALLED" || semanticStatus === "UNKNOWN";
  const style = isFrozen
    ? { bg: "bg-secondary-bg", text: "text-text-secondary", dot: "bg-text-secondary" as const }
    : styles[lifecycleGroup];

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${style.bg} ${style.text}`}
    >
      {lifecycleGroup === "ATTENTION" && !isFrozen && (
        <AlertTriangle className="h-3 w-3" />
      )}
      {lifecycleGroup === "TERMINAL" && !isFrozen && (
        <Check className="h-3 w-3" />
      )}
      {(lifecycleGroup === "ACTIVE" || isFrozen) && style.dot && (
        <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
      )}
      {label}
    </span>
  );
}
