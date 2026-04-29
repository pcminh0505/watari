import { useEffect, useMemo, useState } from "react";
import { useCardSearch } from "../api/cards";
import { useAllSets } from "../api/sets";
import { SearchCardThumbnail } from "../components/cards/SearchCardThumbnail";
import { ErrorMessage } from "../components/ui/ErrorMessage";
import { Pagination } from "../components/ui/Pagination";
import { Spinner } from "../components/ui/Spinner";
import { RARITY_SORT_ORDER } from "../lib/constants";

const PAGE_SIZE = 60;

export function CardsSearchPage() {
  const [input, setInput] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [setCode, setSetCode] = useState("");
  const [rarity, setRarity] = useState("");
  const [page, setPage] = useState(0);

  const { data: sets } = useAllSets();
  const {
    data,
    isPending,
    error,
    refetch,
  } = useCardSearch({ q: debouncedQ, set_code: setCode, rarity, page, limit: PAGE_SIZE });

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(input), 300);
    return () => clearTimeout(t);
  }, [input]);

  useEffect(() => {
    setPage(0);
  }, [debouncedQ, setCode, rarity]);

  const rarityOptions = useMemo(
    () => Object.keys(RARITY_SORT_ORDER).sort((a, b) => RARITY_SORT_ORDER[a] - RARITY_SORT_ORDER[b]),
    []
  );
  const cards = data?.data ?? [];
  const total = data?.total ?? 0;

  return (
    <div>
      <h1 className="mb-4 text-2xl font-bold text-gray-900">Cards</h1>

      <div className="mb-5 rounded-lg border bg-white p-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Search by name, card #, or set code"
          className="mb-3 w-full rounded border px-3 py-2 text-sm"
        />
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <span>Set</span>
            <select
              value={setCode}
              onChange={(e) => setSetCode(e.target.value)}
              className="rounded border px-2 py-1 text-sm"
            >
              <option value="">All</option>
              {(sets ?? []).map((set) => (
                <option key={set.set_code} value={set.set_code}>
                  {set.set_code} - {set.name_ja ?? set.name_en ?? set.set_code}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-2 text-sm text-gray-700">
            <span>Rarity</span>
            <select
              value={rarity}
              onChange={(e) => setRarity(e.target.value)}
              className="rounded border px-2 py-1 text-sm"
            >
              <option value="">All</option>
              {rarityOptions.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {isPending ? (
        <Spinner />
      ) : error ? (
        <ErrorMessage error={error} onRetry={refetch} />
      ) : (
        <>
          <div className="mb-3 text-sm text-gray-500">{total} cards found</div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
            {cards.map((card) => (
              <SearchCardThumbnail key={card.artwork_id} card={card} />
            ))}
          </div>
          <Pagination page={page} total={total} limit={PAGE_SIZE} onPageChange={setPage} />
        </>
      )}
    </div>
  );
}
