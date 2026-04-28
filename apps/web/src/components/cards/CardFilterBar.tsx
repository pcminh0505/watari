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
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5">
          <label htmlFor="rarity-filter" className="text-sm font-medium text-gray-700">
            Rarity
          </label>
          <select
            id="rarity-filter"
            value={rarity}
            onChange={(e) => onRarityChange(e.target.value)}
            className="rounded border px-2 py-1 text-sm"
          >
            <option value="">All</option>
            {availableRarities.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-1.5">
          <label htmlFor="sort-select" className="text-sm font-medium text-gray-700">
            Sort
          </label>
          <select
            id="sort-select"
            value={sort}
            onChange={(e) => onSortChange(e.target.value as SortKey)}
            className="rounded border px-2 py-1 text-sm"
          >
            <option value="number">Card number</option>
            <option value="name_asc">Name (A → Z)</option>
            <option value="name_desc">Name (Z → A)</option>
            <option value="rarity_desc">Rarity (rare first)</option>
            <option value="rarity_asc">Rarity (common first)</option>
          </select>
        </div>

        <label className="flex cursor-pointer items-center gap-1.5 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={trackedOnly}
            onChange={(e) => onTrackedOnlyChange(e.target.checked)}
            className="rounded"
          />
          Tracked only
        </label>
      </div>

      {total > 0 && (
        <span className="text-sm text-gray-400">{total} cards</span>
      )}
    </div>
  );
}
