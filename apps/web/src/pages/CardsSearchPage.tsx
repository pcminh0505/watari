import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { useCardRarities, useCardSearch } from "../api/cards";
import { useAllSets } from "../api/sets";
import type { SortKey } from "../components/cards/CardFilterBar";
import { SearchCardThumbnail } from "../components/cards/SearchCardThumbnail";
import { CardSkeleton } from "../components/cards/CardSkeleton";
import { ErrorMessage } from "../components/ui/ErrorMessage";
import { Pagination } from "../components/ui/Pagination";
import { sortSearchCards } from "../lib/sortSearchCards";

/** Match set page: client-side sort + paginate up to API max per request. */
const FETCH_LIMIT = 500;
const PAGE_SIZE = 60;

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
  const illustratorParam = searchParams.get("illustrator") || "";
  const sort = (searchParams.get("sort") || "number") as SortKey;
  const page = parseInt(searchParams.get("page") || "0", 10);

  const [localQ, setLocalQ] = useState(qParam);
  const debouncedQ = useDebounce(localQ, 300);

  const [localIllustrator, setLocalIllustrator] = useState(illustratorParam);
  const debouncedIllustrator = useDebounce(localIllustrator, 300);

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
    if (illustratorParam !== debouncedIllustrator) {
      updateParams({ illustrator: debouncedIllustrator });
    }
  }, [debouncedIllustrator, illustratorParam]);

  const {
    data,
    isPending,
    error,
    refetch,
  } = useCardSearch({
    q: qParam,
    set_code: setCode,
    rarity: rarityParam,
    illustrator: illustratorParam,
    page: 0,
    limit: FETCH_LIMIT,
  });

  const { data: sets } = useAllSets();
  const { data: rarityOptions } = useCardRarities(setCode);

  useEffect(() => {
    if (!rarityParam || !rarityOptions) return;
    if (!rarityOptions.includes(rarityParam)) {
      updateParams({ rarity: undefined });
    }
  }, [rarityParam, rarityOptions]);

  const allCards = data?.data ?? [];
  const apiTotal = data?.total ?? 0;
  const sorted = useMemo(() => sortSearchCards(allCards, sort), [allCards, sort]);
  const paginationTotal = sorted.length;
  const totalPages =
    paginationTotal === 0 ? 0 : Math.max(1, Math.ceil(paginationTotal / PAGE_SIZE));
  const safePage =
    paginationTotal === 0 ? 0 : Math.min(page, totalPages - 1);
  const pageCards = sorted.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);
  const isTruncated = apiTotal > allCards.length;

  useEffect(() => {
    if (isPending || paginationTotal === 0) return;
    if (page !== safePage) {
      updateParams({ page: safePage === 0 ? undefined : String(safePage) });
    }
  }, [isPending, paginationTotal, page, safePage]);

  return (
    <div>
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
            <select
              value={rarityParam}
              onChange={(e) => updateParams({ rarity: e.target.value })}
              className="w-full appearance-none rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-950 py-2.5 pl-4 pr-10 text-sm text-slate-700 dark:text-slate-300 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            >
              <option value="">All rarities</option>
              {(rarityOptions ?? []).map((rarity) => (
                <option key={rarity} value={rarity}>
                  {rarity}
                </option>
              ))}
            </select>
            <svg className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="flex-1 relative min-w-[10rem]">
            <select
              value={sort}
              onChange={(e) => {
                const v = e.target.value as SortKey;
                updateParams({ sort: v === "number" ? undefined : v, page: undefined });
              }}
              className="w-full appearance-none rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-950 py-2.5 pl-4 pr-10 text-sm text-slate-700 dark:text-slate-300 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            >
              <option value="number">Card number</option>
              <option value="name_asc">Card name (A-Z)</option>
              <option value="name_desc">Card name (Z-A)</option>
              <option value="rarity_desc">Rarity (desc)</option>
              <option value="rarity_asc">Rarity (asc)</option>
              <option value="price_desc">Market price (desc)</option>
              <option value="price_asc">Market price (asc)</option>
            </select>
            <svg className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>

          {/* Active filter chips + clear all */}
          {(setCode || rarityParam || illustratorParam) && (
            <div className="flex flex-wrap items-center gap-2">
              {illustratorParam && (
                <div className="flex items-center gap-1 rounded-full bg-primary-100 dark:bg-primary-900/30 px-2 py-1 text-xs font-medium text-primary-700 dark:text-primary-300">
                  <span>Artist: {illustratorParam}</span>
                  <button
                    onClick={() => { updateParams({ illustrator: undefined }); setLocalIllustrator(""); }}
                    className="ml-1 rounded-full p-0.5 hover:bg-primary-200 dark:hover:bg-primary-800"
                  >
                    <svg className="h-3 w-3" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M4.646 4.646a.5.5 0 0 1 .708 0L8 7.293l2.646-2.647a.5.5 0 0 1 .708.708L8.707 8l2.647 2.646a.5.5 0 0 1-.708.708L8 8.707l-2.646 2.647a.5.5 0 0 1-.708-.708L7.293 8 4.646 5.354a.5.5 0 0 1 0-.708z" />
                    </svg>
                  </button>
                </div>
              )}
              <button
                onClick={() => { updateParams({ set: undefined, rarity: undefined, illustrator: undefined }); setLocalIllustrator(""); }}
                className="text-xs font-medium text-primary-600 dark:text-primary-400 hover:text-primary-800 dark:hover:text-primary-300 hover:underline"
              >
                Clear all filters
              </button>
            </div>
          )}

          <div className="flex flex-col items-end gap-0.5 ml-auto text-xs text-slate-400">
            {isPending ? (
              "…"
            ) : (
              <>
                <span>{apiTotal} cards</span>
                {isTruncated && (
                  <span className="max-w-[14rem] text-right text-amber-600/90 dark:text-amber-400/90">
                    Showing first {allCards.length} — refine search to narrow results
                  </span>
                )}
              </>
            )}
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
      ) : sorted.length === 0 ? (
        <div className="rounded-xl border border-slate-200 dark:border-white/5 bg-white/50 dark:bg-slate-900/50 p-12 text-center shadow-sm">
          <p className="text-slate-500 dark:text-slate-400">No cards found matching your criteria.</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
            {pageCards.map((card) => (
              <SearchCardThumbnail key={card.artwork_id} card={card} />
            ))}
          </div>
          <Pagination
            page={safePage}
            total={paginationTotal}
            limit={PAGE_SIZE}
            onPageChange={(p) => updateParams({ page: p === 0 ? undefined : p.toString() })}
          />
        </>
      )}
    </div>
  );
}
