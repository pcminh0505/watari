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

      {/* Search bar */}
      <div className="mb-5 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        {/* Input row */}
        <div className="relative flex items-center border-b border-gray-100">
          <svg
            className="absolute left-4 h-4 w-4 shrink-0 text-gray-400"
            viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2"
          >
            <circle cx="8.5" cy="8.5" r="5.5" strokeLinecap="round" />
            <path d="M15 15l-3-3" strokeLinecap="round" />
          </svg>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Search by name, card #, or set code…"
            className="w-full bg-transparent py-3 pl-11 pr-10 text-sm text-gray-900 placeholder-gray-400 focus:outline-none"
          />
          {input && (
            <button
              onClick={() => setInput("")}
              className="absolute right-3 rounded p-0.5 text-gray-400 hover:text-gray-600"
              aria-label="Clear search"
            >
              <svg className="h-4 w-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
              </svg>
            </button>
          )}
        </div>

        {/* Filter row */}
        <div className="flex flex-wrap items-center gap-3 px-4 py-2.5">
          {/* Set filter */}
          <div className="relative">
            <select
              value={setCode}
              onChange={(e) => setSetCode(e.target.value)}
              className="appearance-none rounded-md border border-gray-200 bg-gray-50 py-1.5 pl-3 pr-8 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="">All sets</option>
              {(sets ?? []).map((set) => (
                <option key={set.set_code} value={set.set_code}>
                  {set.set_code.toLowerCase()} · {set.name_ja ?? set.name_en ?? set.set_code}
                </option>
              ))}
            </select>
            <svg className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>

          {/* Rarity filter */}
          <div className="relative">
            <select
              value={rarity}
              onChange={(e) => setRarity(e.target.value)}
              className="appearance-none rounded-md border border-gray-200 bg-gray-50 py-1.5 pl-3 pr-8 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="">All rarities</option>
              {rarityOptions.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
            <svg className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>

          {/* Active filter chips + clear all */}
          {(setCode || rarity) && (
            <button
              onClick={() => { setSetCode(""); setRarity(""); }}
              className="text-xs text-blue-600 hover:text-blue-800 hover:underline"
            >
              Clear filters
            </button>
          )}

          <span className="ml-auto text-xs text-gray-400">
            {isPending ? "…" : `${total} cards`}
          </span>
        </div>
      </div>

      {isPending ? (
        <Spinner />
      ) : error ? (
        <ErrorMessage error={error} onRetry={refetch} />
      ) : (
        <>
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
