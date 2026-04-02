import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Calendar, Loader2 } from "lucide-react";
import Header from "@/components/Header";
import StatusBadge from "@/components/StatusBadge";
import Timeline from "@/components/Timeline";
import EventLog from "@/components/EventLog";
import { useDeliveryDetail } from "@/hooks/useDeliveryDetail";
import { useCarriers } from "@/hooks/useCarriers";
import { formatExpectedDate } from "@/utils/dates";

export default function DeliveryDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: delivery, isLoading, isError } = useDeliveryDetail(id);
  const { data: carriersData } = useCarriers();

  const carrierName = carriersData?.carriers.find(
    (c) => c.code === delivery?.carrier_code,
  )?.name;

  return (
    <div className="min-h-screen bg-bg">
      <Header />
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {/* Back link */}
        <Link
          to="/deliveries"
          className="mb-4 inline-flex items-center gap-1 text-sm text-text-secondary hover:text-text transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to deliveries
        </Link>

        {isLoading && (
          <div className="flex justify-center py-20">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        )}

        {isError && (
          <div className="rounded-lg border border-danger bg-danger-bg-light px-6 py-12 text-center">
            <p className="text-sm text-danger">
              Failed to load delivery details.
            </p>
          </div>
        )}

        {delivery && (
          <>
            {/* Header card */}
            <div className="mb-6 rounded-xl border border-border bg-card p-6">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 flex-1">
                  <h1 className="font-heading text-[22px] font-semibold text-text">
                    {delivery.description || delivery.tracking_number}
                  </h1>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-text-secondary">
                    <span className="font-mono text-xs">
                      {delivery.tracking_number}
                    </span>
                    <span className="text-text-muted">&middot;</span>
                    <span>
                      {carrierName ?? delivery.carrier_code}
                    </span>
                  </div>
                  {delivery.extra_information && (
                    <p className="mt-2 text-sm text-text-secondary">
                      {delivery.extra_information}
                    </p>
                  )}
                </div>

                <div className="flex flex-col items-end gap-2">
                  <StatusBadge
                    semanticStatus={delivery.semantic_status}
                    lifecycleGroup={delivery.lifecycle_group}
                  />
                  <div className="flex items-center gap-1 text-sm text-text-secondary">
                    <Calendar className="h-3.5 w-3.5" />
                    <span>
                      {formatExpectedDate(
                        delivery.timestamp_expected,
                        delivery.date_expected_raw,
                      )}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Two-column: status history + events */}
            <div className="grid gap-6 lg:grid-cols-2">
              {/* Status History */}
              <div className="rounded-xl border border-border bg-card p-6">
                <h2 className="mb-4 font-heading text-base font-semibold text-text">
                  Status History
                </h2>
                <Timeline history={delivery.status_history} />
              </div>

              {/* Tracking Events */}
              <div className="rounded-xl border border-border bg-card p-6">
                <h2 className="mb-4 font-heading text-base font-semibold text-text">
                  Tracking Events
                </h2>
                <EventLog events={delivery.events} />
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
