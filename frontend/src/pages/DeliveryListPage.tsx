import { useState, useEffect, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { Search } from "lucide-react";
import Header from "@/components/Header";
import FilterTabs, { type TabValue } from "@/components/FilterTabs";
import DeliveryTable from "@/components/DeliveryTable";
import Pagination from "@/components/Pagination";
import SkeletonTable from "@/components/SkeletonTable";
import { useDeliveries } from "@/hooks/useDeliveries";
import type { LifecycleGroup, SortField, SortDir } from "@/types/api";

const TAB_TO_LIFECYCLE: Record<TabValue, LifecycleGroup | undefined> = {
  all: undefined,
  active: "ACTIVE",
  attention: "ATTENTION",
  delivered: "TERMINAL",
};

const PAGE_SIZE = 20;

export default function DeliveryListPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  // Read state from URL
  const tab = (searchParams.get("tab") as TabValue | null) ?? "all";
  const page = Number(searchParams.get("page")) || 1;
  const sortBy =
    (searchParams.get("sort_by") as SortField | null) ?? "timestamp_expected";
  const sortDir = (searchParams.get("sort_dir") as SortDir | null) ?? "asc";
  const searchFromUrl = searchParams.get("search") ?? "";

  // Local search input for debounce
  const [searchInput, setSearchInput] = useState(searchFromUrl);

  // Debounce search input -> URL param
  useEffect(() => {
    const timeout = setTimeout(() => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (searchInput) {
          next.set("search", searchInput);
        } else {
          next.delete("search");
        }
        next.set("page", "1"); // reset page on search change
        return next;
      });
    }, 300);
    return () => clearTimeout(timeout);
  }, [searchInput, setSearchParams]);

  // Sync URL -> local input when navigating back
  useEffect(() => {
    setSearchInput(searchFromUrl);
  }, [searchFromUrl]);

  // URL update helpers
  const setTab = useCallback(
    (newTab: TabValue) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (newTab === "all") {
          next.delete("tab");
        } else {
          next.set("tab", newTab);
        }
        next.set("page", "1");
        return next;
      });
    },
    [setSearchParams],
  );

  const setPage = useCallback(
    (newPage: number) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("page", String(newPage));
        return next;
      });
    },
    [setSearchParams],
  );

  const handleSort = useCallback(
    (field: SortField) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (field === sortBy) {
          next.set("sort_dir", sortDir === "asc" ? "desc" : "asc");
        } else {
          next.set("sort_by", field);
          next.set("sort_dir", "asc");
        }
        next.set("page", "1");
        return next;
      });
    },
    [setSearchParams, sortBy, sortDir],
  );

  // Build query params
  const lifecycleGroup = TAB_TO_LIFECYCLE[tab];
  const queryParams = useMemo(
    () => ({
      page,
      page_size: PAGE_SIZE,
      lifecycle_group: lifecycleGroup,
      search: searchFromUrl || undefined,
      sort_by: sortBy,
      sort_dir: sortDir,
      include_terminal: tab === "all" || tab === "delivered" ? true : undefined,
    }),
    [page, lifecycleGroup, searchFromUrl, sortBy, sortDir, tab],
  );

  const { data, isLoading, isError } = useDeliveries(queryParams);

  // Separate query for attention count (badge on tab)
  const { data: attentionData } = useDeliveries({
    page: 1,
    page_size: 1,
    lifecycle_group: "ATTENTION",
  });
  const attentionCount = attentionData?.total ?? 0;

  return (
    <div className="min-h-screen bg-bg">
      <Header />
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {/* Toolbar */}
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <FilterTabs
            activeTab={tab}
            onTabChange={setTab}
            attentionCount={attentionCount}
          />

          {/* Search */}
          <div className="relative w-full sm:w-[280px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
            <input
              type="text"
              placeholder="Search deliveries..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="w-full rounded-lg border border-input-border bg-card py-1.5 pl-9 pr-3 text-sm text-text placeholder:text-text-muted outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/20"
            />
          </div>
        </div>

        {/* Content */}
        {isLoading && !data ? (
          <SkeletonTable />
        ) : isError ? (
          <div className="rounded-lg border border-danger bg-danger-bg-light px-6 py-12 text-center">
            <p className="text-sm text-danger">
              Failed to load deliveries. Please try again.
            </p>
          </div>
        ) : data ? (
          <>
            <DeliveryTable
              items={data.items}
              sortBy={sortBy}
              sortDir={sortDir}
              onSort={handleSort}
            />
            <Pagination
              page={data.page}
              pages={data.pages}
              onPageChange={setPage}
            />
          </>
        ) : null}
      </main>
    </div>
  );
}
