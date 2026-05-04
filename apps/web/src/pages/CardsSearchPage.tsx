import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { useCardSearch } from "../api/cards";
import { useAllSets } from "../api/sets";
import { SearchCardThumbnail } from "../components/cards/SearchCardThumbnail";
import { CardSkeleton } from "../components/cards/CardSkeleton";
import { ErrorMessage } from "../components/ui/ErrorMessage";
import { Pagination } from "../components/ui/Pagination";

const PAGE_SIZE = 50;

function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debouncedValue;
}

export function CardsSearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const qParam = searchParams.get("q") || "";
  const setCode = searchParams.get("set") || "";
  const rarityParam = searchParams.get("rarity") || "";
  const page = parseInt(searchParams.get("page") || "0", 10);

  const [localQ, setLocalQ] = useState(qParam);
  const debouncedQ = useDebounce(localQ, 300);

  const [localRarity, setLocalRarity] = useState(rarityParam);
  const debouncedRarity = useDebounce(localRarity, 300);

  function updateParams(updates: Record<string, string | undefined>) {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev);
      Object.entries(updates).forEach(([key, value]) => {
        if (value === undefined || value === "") {
          next.delete(key);
        } else {
          next.set(key, value);
        }
      });
      if (!updates.hasOwnProperty("page")) {
        next.delete("page");
      }
      return next;
    }, { replace: true });
  }

  useEffect(() => {
    if (qParam !== debouncedQ) {
      updateParams({ q: debouncedQ });
    }
  }, [debouncedQ, qParam]);

  useEffect(() => {
    if (rarityParam !== debouncedRarity) {
      updateParams({ rarity: debouncedRarity });
    }
  }, [debouncedRarity, rarityParam]);

  const {
    data,
    isPending,
    error,
    refetch,
  } = useCardSearch({ q: qParam, set_code: setCode, rarity: rarityParam, page, limit: PAGE_SIZE });

  const { data: sets } = useAllSets();

  const cards = data?.data ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="mb-8 text-3xl font-bold text-slate-900 dark:text-slate-50 text-glow">
        Search Cards
      </h1>

      {/* Search Controls */}
      <div className="mb-8 space-y-4 rounded-xl border border-slate-200 dark:border-white/10 bg-white/50 dark:bg-slate-900/50 p-4 shadow-sm backdrop-blur-md">
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-slate-400" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="8.5" cy="8.5" r="5.5" strokeLinecap="round" />
            <path d="M15 15l-3-3" strokeLinecap="round" />
          </svg>
          <input
            type="text"
            value={localQ}
            onChange={(e) => setLocalQ(e.target.value)}
            placeholder="Search by card name or ID..."
            className="w-full appearance-none rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-950 py-3 pl-10 pr-4 text-slate-900 dark:text-slate-100 shadow-inner focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="flex-1 relative">
            <select
              value={setCode}
              onChange={(e) => updateParams({ set: e.target.value })}
              className="w-full appearance-none rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-950 py-2.5 pl-4 pr-10 text-sm text-slate-700 dark:text-slate-300 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            >
              <option value="">All sets</option>
              {(sets ?? []).map((set) => (
                <option key={set.set_code} value={set.set_code}>
                  {set.set_code.toLowerCase()} · {set.name_en ?? set.name_ja ?? set.set_code}
                </option>
              ))}
            </select>
            <svg className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="flex-1 relative">
            <input
              type="text"
              value={localRarity}
              onChange={(e) => setLocalRarity(e.target.value)}
              placeholder="Rarity (e.g. SAR, UR)"
              className="w-full appearance-none rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-950 py-2.5 pl-4 pr-4 text-sm text-slate-700 dark:text-slate-300 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            />
          </div>

          {/* Active filter chips + clear all */}
          {(setCode || rarityParam) && (
            <button
              onClick={() => { updateParams({ set: undefined, rarity: undefined }); setLocalRarity(""); }}
              className="text-xs font-medium text-primary-600 dark:text-primary-400 hover:text-primary-800 dark:hover:text-primary-300 hover:underline"
            >
              Clear filters
            </button>
          )}

          <div className="flex items-center ml-auto text-xs text-slate-400">
            {isPending ? "…" : `${total} cards`}
          </div>
        </div>
      </div>

      {isPending ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
          {Array.from({ length: 18 }).map((_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : error ? (
        <ErrorMessage error={error} onRetry={refetch} />
      ) : cards.length === 0 ? (
        <div className="rounded-xl border border-slate-200 dark:border-white/5 bg-white/50 dark:bg-slate-900/50 p-12 text-center shadow-sm">
          <p className="text-slate-500 dark:text-slate-400">No cards found matching your criteria.</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
            {cards.map((card) => (
              <SearchCardThumbnail key={card.artwork_id} card={card} />
            ))}
          </div>
          <Pagination page={page} total={total} limit={PAGE_SIZE} onPageChange={(p) => updateParams({ page: p === 0 ? undefined : p.toString() })} />
        </>
      )}
    </div>
  );
}
