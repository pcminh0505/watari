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
    <div className="mb-5 rounded-lg border bg-white p-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button
          className={`rounded-full px-3 py-1 text-sm ${era === "all" ? "bg-gray-900 text-white" : "bg-gray-100 text-gray-600"}`}
          onClick={() => onEraChange("all")}
        >
          All
        </button>
        <button
          className={`rounded-full px-3 py-1 text-sm ${era === "me" ? "bg-gray-900 text-white" : "bg-gray-100 text-gray-600"}`}
          onClick={() => onEraChange("me")}
        >
          Mega Evolution
        </button>
        <button
          className={`rounded-full px-3 py-1 text-sm ${era === "sv" ? "bg-gray-900 text-white" : "bg-gray-100 text-gray-600"}`}
          onClick={() => onEraChange("sv")}
        >
          Scarlet & Violet
        </button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <span>Sort</span>
          <select
            value={sort}
            onChange={(e) => onSortChange(e.target.value as SetSort)}
            className="rounded border px-2 py-1 text-sm"
          >
            <option value="release_desc">Release date (new to old)</option>
            <option value="release_asc">Release date (old to new)</option>
            <option value="value_desc">Set value (high to low)</option>
            <option value="value_asc">Set value (low to high)</option>
          </select>
        </label>
        <span className="text-sm text-gray-500">{total} sets</span>
      </div>
    </div>
  );
}
