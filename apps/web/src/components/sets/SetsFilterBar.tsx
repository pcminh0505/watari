import clsx from "clsx";

type EraFilter = "all" | "sv" | "me" | "sm" | "sw";
type SetSort = "release_desc" | "release_asc" | "value_desc" | "value_asc";

interface SetsFilterBarProps {
  era: EraFilter;
  onEraChange: (era: EraFilter) => void;
  sort: SetSort;
  onSortChange: (sort: SetSort) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  total: number;
}

export function SetsFilterBar({
  era,
  onEraChange,
  sort,
  onSortChange,
  searchQuery,
  onSearchChange,
  total,
}: SetsFilterBarProps) {
  return (
    <div className="mb-6 space-y-4">
      {/* Era pills */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-2 text-xs font-semibold text-slate-500 uppercase tracking-widest">Era</span>
        {(["all", "me", "sv", "sw", "sm"] as EraFilter[]).map((e) => (
          <button
            key={e}
            onClick={() => onEraChange(e)}
            className={clsx(
              "rounded-full px-4 py-1.5 text-xs font-medium transition-all border",
              era === e
                ? "bg-primary-50 text-primary-700 border-primary-500 dark:bg-primary-900/40 dark:text-primary-300 dark:border-primary-500/50 shadow-sm dark:shadow-[0_0_10px_rgba(14,165,233,0.3)]"
                : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50 hover:text-slate-900 dark:bg-white/5 dark:text-slate-400 dark:border-white/5 dark:hover:bg-white/10 dark:hover:text-white"
            )}
          >
            {e === "all"
              ? "All"
              : e === "sv"
                ? "Scarlet & Violet"
                : e === "me"
                  ? "Mega Evolution"
                  : e === "sm"
                    ? "Sun & Moon"
                    : "Sword & Shield"}
          </button>
        ))}
      </div>

      {/* Sort & Search row */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        {/* Search Input */}
        <div className="relative flex-1 max-w-md">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="8.5" cy="8.5" r="5.5" strokeLinecap="round" />
            <path d="M15 15l-3-3" strokeLinecap="round" />
          </svg>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search by code or name..."
            className="w-full appearance-none rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-900/80 py-2 pl-9 pr-8 text-sm text-slate-700 dark:text-slate-300 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 transition-colors"
          />
          {searchQuery && (
            <button
              onClick={() => onSearchChange("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
            >
              <svg className="h-4 w-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
              </svg>
            </button>
          )}
        </div>

        <div className="flex items-center gap-4">
          {total > 0 && (
            <span className="text-sm font-medium text-slate-500 hidden sm:inline-block">{total} sets</span>
          )}
          <div className="relative w-full sm:w-auto">
            <select
              value={sort}
              onChange={(e) => onSortChange(e.target.value as SetSort)}
              className="w-full sm:w-auto appearance-none rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-900/80 py-2 pl-4 pr-10 text-sm text-slate-700 dark:text-slate-300 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 transition-colors"
            >
              <option value="release_desc">Release date (new → old)</option>
              <option value="release_asc">Release date (old → new)</option>
              <option value="value_desc">Set value (high → low)</option>
              <option value="value_asc">Set value (low → high)</option>
            </select>
            <svg
              className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 dark:text-slate-500"
              viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8"
            >
              <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
        </div>
      </div>
    </div>
  );
}
