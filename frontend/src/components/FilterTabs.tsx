export type TabValue = "all" | "active" | "attention" | "delivered";

interface FilterTabsProps {
  activeTab: TabValue;
  onTabChange: (tab: TabValue) => void;
  attentionCount: number;
}

const TABS: Array<{ value: TabValue; label: string }> = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "attention", label: "Needs Attention" },
  { value: "delivered", label: "Delivered" },
];

export default function FilterTabs({
  activeTab,
  onTabChange,
  attentionCount,
}: FilterTabsProps) {
  return (
    <div className="flex gap-1">
      {TABS.map((tab) => {
        const isActive = activeTab === tab.value;
        return (
          <button
            key={tab.value}
            onClick={() => onTabChange(tab.value)}
            className={`
              relative rounded-md px-3 py-1.5 text-sm font-medium transition-colors
              ${
                isActive
                  ? "bg-card text-text border border-border shadow-sm"
                  : "text-text-secondary hover:text-text hover:bg-card/50"
              }
            `}
          >
            {tab.label}
            {tab.value === "attention" && attentionCount > 0 && (
              <span className="ml-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-semibold text-white">
                {attentionCount}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
