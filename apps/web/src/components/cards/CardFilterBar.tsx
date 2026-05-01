import clsx from "clsx";

export type SortKey =
  | "number"
  | "name_asc"
  | "name_desc"
  | "rarity_desc"
  | "rarity_asc";

interface CardFilterBarProps {
  rarity: string;
  onRarityChange: (rarity: string) => void;
  trackedOnly: boolean;
  onTrackedOnlyChange: (v: boolean) => void;
  sort: SortKey;
  onSortChange: (sort: SortKey) => void;
  availableRarities: string[];
  total: number;
}

export function CardFilterBar({
  rarity,
  onRarityChange,
  trackedOnly,
  onTrackedOnlyChange,
  sort,
  onSortChange,
  availableRarities,
  total,
}: CardFilterBarProps) {
  return (
    <div className="mb-5 space-y-3">
      {/* Rarity pills */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs font-medium text-gray-500 uppercase tracking-wide">Rarity</span>
        <button
          onClick={() => onRarityChange("")}
          className={clsx(
            "rounded-full px-3 py-1 text-xs font-medium transition",
            rarity === ""
              ? "bg-gray-900 text-white"
              : "bg-gray-100 text-gray-600 hover:bg-gray-200"
          )}
        >
          All
        </button>
        {availableRarities.map((r) => (
          <button
            key={r}
            onClick={() => onRarityChange(rarity === r ? "" : r)}
            className={clsx(
              "rounded-full px-3 py-1 text-xs font-medium transition",
              rarity === r
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            )}
          >
            {r}
          </button>
        ))}
      </div>

      {/* Sort + tracked row */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          {/* Sort */}
          <div className="relative">
            <select
              id="sort-select"
              value={sort}
              onChange={(e) => onSortChange(e.target.value as SortKey)}
              className="appearance-none rounded-md border border-gray-200 bg-white py-1.5 pl-3 pr-8 text-sm text-gray-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="number">Card number</option>
              <option value="name_asc">Name A → Z</option>
              <option value="name_desc">Name Z → A</option>
              <option value="rarity_desc">Rarest first</option>
              <option value="rarity_asc">Common first</option>
            </select>
            <svg
              className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400"
              viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8"
            >
              <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>

          {/* Tracked only toggle */}
          <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-600">
            <span
              className={clsx(
                "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200",
                trackedOnly ? "bg-blue-600" : "bg-gray-200"
              )}
              onClick={() => onTrackedOnlyChange(!trackedOnly)}
            >
              <span
                className={clsx(
                  "pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transition-transform duration-200",
                  trackedOnly ? "translate-x-4" : "translate-x-0"
                )}
              />
            </span>
            Tracked only
          </label>
        </div>

        {total > 0 && (
          <span className="text-sm text-gray-400">{total} cards</span>
        )}
      </div>
    </div>
  );
}
