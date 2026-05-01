import clsx from "clsx";

type EraFilter = "all" | "sv" | "me";
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
    <div className="mb-5 space-y-3">
      {/* Era pills */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs font-medium text-gray-500 uppercase tracking-wide">Era</span>
        {(["all", "sv", "me"] as EraFilter[]).map((e) => (
          <button
            key={e}
            onClick={() => onEraChange(e)}
            className={clsx(
              "rounded-full px-3 py-1 text-xs font-medium transition",
              era === e
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            )}
          >
            {e === "all" ? "All" : e === "sv" ? "Scarlet & Violet" : "Mega Evolution"}
          </button>
        ))}
      </div>

      {/* Sort row */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="relative">
          <select
            value={sort}
            onChange={(e) => onSortChange(e.target.value as SetSort)}
            className="appearance-none rounded-md border border-gray-200 bg-white py-1.5 pl-3 pr-8 text-sm text-gray-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="release_desc">Release date (new → old)</option>
            <option value="release_asc">Release date (old → new)</option>
            <option value="value_desc">Set value (high → low)</option>
            <option value="value_asc">Set value (low → high)</option>
          </select>
          <svg
            className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400"
            viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8"
          >
            <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>

        {total > 0 && (
          <span className="text-sm text-gray-400">{total} sets</span>
        )}
      </div>
    </div>
  );
}
