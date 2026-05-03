import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { useCards } from "../api/cards";
import { useSet } from "../api/sets";
import type { SortKey } from "../components/cards/CardFilterBar";
import { CardFilterBar } from "../components/cards/CardFilterBar";
import { CardGrid } from "../components/cards/CardGrid";
import { ErrorMessage } from "../components/ui/ErrorMessage";
import { Pagination } from "../components/ui/Pagination";
import { Spinner } from "../components/ui/Spinner";
import { RARITY_SORT_ORDER } from "../lib/constants";
import type { ArtworkDetail } from "../types/api";

const PAGE_SIZE = 60;

function sortCards(cards: ArtworkDetail[], sort: SortKey): ArtworkDetail[] {
  const rarityOrder = (code: string | null) =>
    RARITY_SORT_ORDER[code ?? ""] ?? 99;

  return [...cards].sort((a, b) => {
    switch (sort) {
      case "number":
        return a.local_id.localeCompare(b.local_id);
      case "name_asc": {
        const na = a.name_ja ?? a.name_en ?? a.local_id;
        const nb = b.name_ja ?? b.name_en ?? b.local_id;
        return na.localeCompare(nb, "ja");
      }
      case "name_desc": {
        const na = a.name_ja ?? a.name_en ?? a.local_id;
        const nb = b.name_ja ?? b.name_en ?? b.local_id;
        return nb.localeCompare(na, "ja");
      }
      case "rarity_desc":
        return rarityOrder(b.rarity_code) - rarityOrder(a.rarity_code);
      case "rarity_asc":
        return rarityOrder(a.rarity_code) - rarityOrder(b.rarity_code);
    }
  });
}

export function CardsPage() {
  const { setCode = "" } = useParams<{ setCode: string }>();
  const [rarity, setRarity] = useState("");
  // Default off: catalog artworks exist before scrapers mark prints tracked.
  const [trackedOnly, setTrackedOnly] = useState(false);
  const [sort, setSort] = useState<SortKey>("number");
  const [page, setPage] = useState(0);

  const { data: set } = useSet(setCode);
  // Fetch all cards without rarity filter so rarity is derived dynamically
  // and filtering/sorting compose correctly client-side.
  const { data, isPending, error, refetch } = useCards(setCode, {
    tracked_only: trackedOnly,
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

  const filtered = useMemo(
    () => (rarity ? allCards.filter((c) => c.rarity_code === rarity) : allCards),
    [allCards, rarity]
  );

  const sorted = useMemo(() => sortCards(filtered, sort), [filtered, sort]);
  const pageCards = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const setName = set ? (set.name_ja ?? set.name_en ?? setCode) : setCode;

  function handleRarityChange(v: string) { setRarity(v); setPage(0); }
  function handleTrackedOnlyChange(v: boolean) { setTrackedOnly(v); setPage(0); }
  function handleSortChange(v: SortKey) { setSort(v); setPage(0); }

  return (
    <div>
      <div className="mb-4 flex items-center gap-2 text-sm text-neutral-400">
        <Link to="/" className="hover:text-white transition-colors">Sets</Link>
        <span>/</span>
        <span className="text-neutral-50">{setName}</span>
      </div>
      <h1 className="mb-6 text-3xl font-bold text-neutral-50 text-glow">
        {setName}
        <span className="ml-3 text-lg font-normal text-primary-400">{setCode}</span>
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
        <Spinner />
      ) : error ? (
        <ErrorMessage error={error} onRetry={refetch} />
      ) : (
        <>
          <CardGrid cards={pageCards} />
          <Pagination
            page={page}
            total={sorted.length}
            limit={PAGE_SIZE}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}
