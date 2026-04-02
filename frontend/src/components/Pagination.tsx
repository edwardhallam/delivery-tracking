import { ChevronLeft, ChevronRight } from "lucide-react";

interface PaginationProps {
  page: number;
  pages: number;
  onPageChange: (page: number) => void;
}

export default function Pagination({
  page,
  pages,
  onPageChange,
}: PaginationProps) {
  if (pages <= 1) return null;

  return (
    <div className="flex items-center justify-between border-t border-border px-4 py-3">
      <button
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
        className="flex items-center gap-1 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium text-text-secondary transition-colors hover:bg-secondary-bg disabled:cursor-not-allowed disabled:opacity-40"
      >
        <ChevronLeft className="h-4 w-4" />
        Previous
      </button>

      <span className="text-sm text-text-secondary">
        Page {page} of {pages}
      </span>

      <button
        onClick={() => onPageChange(page + 1)}
        disabled={page >= pages}
        className="flex items-center gap-1 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium text-text-secondary transition-colors hover:bg-secondary-bg disabled:cursor-not-allowed disabled:opacity-40"
      >
        Next
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  );
}
