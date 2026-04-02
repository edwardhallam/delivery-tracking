import { useNavigate } from "react-router-dom";
import { ArrowUp, ArrowDown } from "lucide-react";
import StatusBadge from "@/components/StatusBadge";
import { formatExpectedDate } from "@/utils/dates";
import { useCarriers } from "@/hooks/useCarriers";
import type { DeliverySummary, SortField, SortDir } from "@/types/api";

interface DeliveryTableProps {
  items: DeliverySummary[];
  sortBy: SortField;
  sortDir: SortDir;
  onSort: (field: SortField) => void;
}

const SORT_COLUMNS: Array<{
  field: SortField;
  label: string;
  className: string;
}> = [
  { field: "timestamp_expected", label: "Expected", className: "hidden md:table-cell" },
  { field: "carrier_code", label: "Carrier", className: "hidden sm:table-cell" },
  { field: "updated_at", label: "Status", className: "" },
];

function SortIcon({
  field,
  sortBy,
  sortDir,
}: {
  field: SortField;
  sortBy: SortField;
  sortDir: SortDir;
}) {
  if (field !== sortBy) return null;
  return sortDir === "asc" ? (
    <ArrowUp className="ml-0.5 inline h-3 w-3" />
  ) : (
    <ArrowDown className="ml-0.5 inline h-3 w-3" />
  );
}

export default function DeliveryTable({
  items,
  sortBy,
  sortDir,
  onSort,
}: DeliveryTableProps) {
  const navigate = useNavigate();
  const { data: carriersData } = useCarriers();

  const carrierMap = new Map(
    carriersData?.carriers.map((c) => [c.code, c.name]) ?? [],
  );

  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card px-6 py-12 text-center">
        <p className="text-sm text-text-secondary">
          No deliveries found matching your filters.
        </p>
      </div>
    );
  }

  return (
    <>
      {/* Desktop table */}
      <div className="hidden overflow-hidden rounded-lg border border-border bg-card sm:block">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border bg-secondary-bg/50">
              <th className="px-4 py-2.5 text-left text-xs font-medium text-text-secondary">
                Description
              </th>
              {SORT_COLUMNS.map((col) => (
                <th
                  key={col.field}
                  className={`cursor-pointer px-4 py-2.5 text-left text-xs font-medium text-text-secondary hover:text-text ${col.className}`}
                  onClick={() => onSort(col.field)}
                >
                  {col.label}
                  <SortIcon field={col.field} sortBy={sortBy} sortDir={sortDir} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {items.map((d) => (
              <tr
                key={d.id}
                onClick={() => navigate(`/deliveries/${d.id}`)}
                className="cursor-pointer transition-colors hover:bg-secondary-bg/30"
              >
                <td className="px-4 py-3">
                  <div className="text-sm font-medium text-text">
                    {d.description || d.tracking_number}
                  </div>
                  {d.description && (
                    <div className="text-xs text-text-muted">
                      {d.tracking_number}
                    </div>
                  )}
                </td>
                <td className="hidden px-4 py-3 md:table-cell">
                  <span className="text-sm text-text-secondary">
                    {formatExpectedDate(
                      d.timestamp_expected,
                      d.date_expected_raw,
                    )}
                  </span>
                </td>
                <td className="hidden px-4 py-3 sm:table-cell">
                  <span className="text-sm text-text-secondary">
                    {carrierMap.get(d.carrier_code) ?? d.carrier_code}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <StatusBadge
                    semanticStatus={d.semantic_status}
                    lifecycleGroup={d.lifecycle_group}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <div className="flex flex-col gap-2 sm:hidden">
        {items.map((d) => (
          <button
            key={d.id}
            onClick={() => navigate(`/deliveries/${d.id}`)}
            className="w-full rounded-lg border border-border bg-card p-3 text-left transition-colors hover:bg-secondary-bg/30"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-text">
                  {d.description || d.tracking_number}
                </div>
                {d.description && (
                  <div className="truncate text-xs text-text-muted">
                    {d.tracking_number}
                  </div>
                )}
              </div>
              <StatusBadge
                semanticStatus={d.semantic_status}
                lifecycleGroup={d.lifecycle_group}
              />
            </div>
            <div className="mt-2 flex items-center gap-3 text-xs text-text-secondary">
              <span>{carrierMap.get(d.carrier_code) ?? d.carrier_code}</span>
              <span className="text-text-muted">
                {formatExpectedDate(d.timestamp_expected, d.date_expected_raw)}
              </span>
            </div>
          </button>
        ))}
      </div>
    </>
  );
}
