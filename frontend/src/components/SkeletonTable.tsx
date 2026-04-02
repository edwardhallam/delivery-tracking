function SkeletonRow() {
  return (
    <tr className="animate-pulse">
      <td className="px-4 py-3">
        <div className="h-4 w-48 rounded bg-border" />
        <div className="mt-1 h-3 w-28 rounded bg-border/60" />
      </td>
      <td className="hidden px-4 py-3 sm:table-cell">
        <div className="h-4 w-16 rounded bg-border" />
      </td>
      <td className="px-4 py-3">
        <div className="h-5 w-20 rounded-full bg-border" />
      </td>
      <td className="hidden px-4 py-3 md:table-cell">
        <div className="h-4 w-24 rounded bg-border" />
      </td>
    </tr>
  );
}

interface SkeletonTableProps {
  rows?: number;
}

export default function SkeletonTable({ rows = 8 }: SkeletonTableProps) {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <table className="w-full">
        <thead>
          <tr className="border-b border-border bg-secondary-bg/50">
            <th className="px-4 py-2.5 text-left text-xs font-medium text-text-secondary">
              Description
            </th>
            <th className="hidden px-4 py-2.5 text-left text-xs font-medium text-text-secondary sm:table-cell">
              Carrier
            </th>
            <th className="px-4 py-2.5 text-left text-xs font-medium text-text-secondary">
              Status
            </th>
            <th className="hidden px-4 py-2.5 text-left text-xs font-medium text-text-secondary md:table-cell">
              Expected
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {Array.from({ length: rows }, (_, i) => (
            <SkeletonRow key={i} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
