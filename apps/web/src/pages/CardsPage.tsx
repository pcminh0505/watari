import { useMemo } from "react";
import { Link, useParams } from "react-router";
import { useSearchParams } from "react-router";
import { useCardSearch } from "../api/cards";
import { useSet } from "../api/sets";
import type { SortKey } from "../components/cards/CardFilterBar";
import { CardFilterBar } from "../components/cards/CardFilterBar";
import { CardGrid } from "../components/cards/CardGrid";
import { CardSkeleton } from "../components/cards/CardSkeleton";
import { ErrorMessage } from "../components/ui/ErrorMessage";
import { Pagination } from "../components/ui/Pagination";
import { RARITY_SORT_ORDER } from "../lib/constants";
import type { ArtworkSearchResult } from "../types/api";

const PAGE_SIZE = 60;

function sortCards(cards: ArtworkSearchResult[], sort: SortKey): ArtworkSearchResult[] {
  const rarityOrder = (code: string | null) =>
    RARITY_SORT_ORDER[code ?? ""] ?? 99;

  return [...cards].sort((a, b) => {
    switch (sort) {
      case "number":
        return a.local_id.localeCompare(b.local_id);
      case "name_asc": {
        const na = a.name_en ?? a.name_ja ?? a.local_id;
        const nb = b.name_en ?? b.name_ja ?? b.local_id;
        return na.localeCompare(nb, "en");
      }
      case "name_desc": {
        const na = a.name_en ?? a.name_ja ?? a.local_id;
        const nb = b.name_en ?? b.name_ja ?? b.local_id;
        return nb.localeCompare(na, "en");
      }
      case "rarity_desc":
        return rarityOrder(b.rarity_code) - rarityOrder(a.rarity_code);
      case "rarity_asc":
        return rarityOrder(a.rarity_code) - rarityOrder(b.rarity_code);
      case "price_desc":
        return (b.cardrush_a_floor_jpy ?? -1) - (a.cardrush_a_floor_jpy ?? -1);
      case "price_asc":
        return (a.cardrush_a_floor_jpy ?? Infinity) - (b.cardrush_a_floor_jpy ?? Infinity);
    }
  });
}

export function CardsPage() {
  const { setCode = "" } = useParams<{ setCode: string }>();

  const [searchParams, setSearchParams] = useSearchParams();
  const rarity = searchParams.get("rarity") || "";
  const trackedOnly = searchParams.get("tracked") === "true";
  const sort = (searchParams.get("sort") || "number") as SortKey;
  const page = parseInt(searchParams.get("page") || "0", 10);

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

  const { data: set } = useSet(setCode);
  // Fetch all cards for the set using the search endpoint to get price data
  const { data, isPending, error, refetch } = useCardSearch({
    set_code: setCode,
    limit: 500,
  });

  const allCards = data?.data ?? [];

  // Derive rarities present in this set, ordered by RARITY_SORT_ORDER
  // with any unknown rarities (ME-era MUR, MA, etc.) appended alphabetically.
  const availableRarities = useMemo(() => {
    const seen = new Set(
      allCards.map((c) => c.rarity_code).filter((r): r is string => r != null)
    );
    return [...seen].sort((a, b) => {
      const oa = RARITY_SORT_ORDER[a] ?? 99;
      const ob = RARITY_SORT_ORDER[b] ?? 99;
      return oa !== ob ? oa - ob : a.localeCompare(b);
    });
  }, [allCards]);

  const filtered = useMemo(() => {
    let result = allCards;
    if (rarity) result = result.filter((c) => c.rarity_code === rarity);
    if (trackedOnly) result = result.filter((c) => c.variants.some((v) => v.is_tracked));
    return result;
  }, [allCards, rarity, trackedOnly]);

  const sorted = useMemo(() => sortCards(filtered, sort), [filtered, sort]);
  const pageCards = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const setName = set ? (set.name_en ?? set.name_ja ?? setCode.toLowerCase()) : setCode.toLowerCase();

  function handleRarityChange(v: string) { updateParams({ rarity: v }); }
  function handleTrackedOnlyChange(v: boolean) { updateParams({ tracked: v ? "true" : undefined }); }
  function handleSortChange(v: SortKey) { updateParams({ sort: v === "number" ? undefined : v }); }

  return (
    <div>
      <div className="mb-4 flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
        <Link to="/" className="hover:text-slate-900 dark:hover:text-white transition-colors">Sets</Link>
        <span>/</span>
        <span className="text-slate-900 dark:text-slate-50">{setName}</span>
      </div>
      <h1 className="mb-6 text-3xl font-bold text-slate-900 dark:text-slate-50 text-glow">
        {setName}
        <span className="ml-3 text-lg font-normal text-primary-600 dark:text-primary-400">{setCode.toLowerCase()}</span>
      </h1>

      <CardFilterBar
        rarity={rarity}
        onRarityChange={handleRarityChange}
        trackedOnly={trackedOnly}
        onTrackedOnlyChange={handleTrackedOnlyChange}
        sort={sort}
        onSortChange={handleSortChange}
        availableRarities={availableRarities}
        total={sorted.length}
      />

      {isPending ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
          {Array.from({ length: 24 }).map((_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : error ? (
        <ErrorMessage error={error} onRetry={refetch} />
      ) : (
        <>
          <CardGrid cards={pageCards} />
          <Pagination
            page={page}
            total={sorted.length}
            limit={PAGE_SIZE}
            onPageChange={(p) => updateParams({ page: p === 0 ? undefined : p.toString() })}
          />
        </>
      )}
    </div>
  );
}
