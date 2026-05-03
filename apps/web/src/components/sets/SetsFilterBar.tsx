import clsx from "clsx";

type EraFilter = "all" | "sv" | "me" | "sm" | "sw";
type SetSort = "release_desc" | "release_asc" | "value_desc" | "value_asc";

interface SetsFilterBarProps {
  era: EraFilter;
  onEraChange: (era: EraFilter) => void;
  sort: SetSort;
  onSortChange: (sort: SetSort) => void;
  total: number;
}

export function SetsFilterBar({
  era,
  onEraChange,
  sort,
  onSortChange,
  total,
}: SetsFilterBarProps) {
  return (
    <div className="mb-6 space-y-4">
      {/* Era pills */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-2 text-xs font-semibold text-neutral-500 uppercase tracking-widest">Era</span>
        {(["all", "me", "sv", "sw", "sm"] as EraFilter[]).map((e) => (
          <button
            key={e}
            onClick={() => onEraChange(e)}
            className={clsx(
              "rounded-full px-4 py-1.5 text-xs font-medium transition-all border",
              era === e
                ? "bg-primary-600/20 text-primary-400 border-primary-500/50 shadow-[0_0_10px_rgba(168,85,247,0.3)]"
                : "bg-white/5 text-neutral-400 border-white/5 hover:bg-white/10 hover:text-white"
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

      {/* Sort row */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="relative">
          <select
            value={sort}
            onChange={(e) => onSortChange(e.target.value as SetSort)}
            className="appearance-none rounded-lg border border-white/10 bg-neutral-900/80 py-2 pl-4 pr-10 text-sm text-neutral-300 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 transition-colors"
          >
            <option value="release_desc">Release date (new → old)</option>
            <option value="release_asc">Release date (old → new)</option>
            <option value="value_desc">Set value (high → low)</option>
            <option value="value_asc">Set value (low → high)</option>
          </select>
          <svg
            className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-neutral-500"
            viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8"
          >
            <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>

        {total > 0 && (
          <span className="text-sm font-medium text-neutral-500">{total} sets</span>
        )}
      </div>
    </div>
  );
}
