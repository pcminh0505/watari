import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { useAllSets } from "../api/sets";
import { SetCard } from "../components/sets/SetCard";
import { SetCardSkeleton } from "../components/sets/SetCardSkeleton";
import { SetsFilterBar } from "../components/sets/SetsFilterBar";
import { ErrorMessage } from "../components/ui/ErrorMessage";
import { Pagination } from "../components/ui/Pagination";
import { SET_RELEASE_ORDER } from "../lib/constants";
import type { SetOut } from "../types/api";

export function SetsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const era = (searchParams.get("era") || "all") as "all" | "sv" | "me" | "sm" | "sw";
  const sort = (searchParams.get("sort") || "release_desc") as "release_desc" | "release_asc" | "value_desc" | "value_asc";
  const q = searchParams.get("q") || "";
  const page = parseInt(searchParams.get("page") || "0", 10);
  
  const PAGE_SIZE = 50;

  // Local state for instant typing, synced to URL via debounce
  const [localQ, setLocalQ] = useState(q);

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
    const t = setTimeout(() => {
      if (q !== localQ) {
        updateParams({ q: localQ });
      }
    }, 300);
    return () => clearTimeout(t);
  }, [localQ, q]);

  const sortParams =
    sort === "release_desc"
      ? { sort: "release_date" as const, order: "desc" as const }
      : sort === "release_asc"
        ? { sort: "release_date" as const, order: "asc" as const }
        : sort === "value_desc"
          ? { sort: "value" as const, order: "desc" as const }
          : { sort: "value" as const, order: "asc" as const };

  const { data: sets, isPending, error, refetch } = useAllSets({
    era: era === "all" ? undefined : era,
    ...sortParams,
  });

  const displaySets = useMemo(() => {
    let items = [...(sets ?? [])];
    
    if (q.trim()) {
      const query = q.toLowerCase();
      items = items.filter(
        (s) =>
          s.set_code.toLowerCase().includes(query) ||
          (s.name_en && s.name_en.toLowerCase().includes(query)) ||
          (s.name_ja && s.name_ja.toLowerCase().includes(query))
      );
    }

    if (sort === "value_desc" || sort === "value_asc") return items;

    const releaseRank = (set: SetOut) => SET_RELEASE_ORDER[set.set_code] ?? 9999;

    return items.sort((a, b) => {
      const aDate = a.release_date ? new Date(a.release_date).getTime() : null;
      const bDate = b.release_date ? new Date(b.release_date).getTime() : null;

      if (aDate != null && bDate != null) {
        return sort === "release_desc" ? bDate - aDate : aDate - bDate;
      }
      if (aDate != null && bDate == null) return -1;
      if (aDate == null && bDate != null) return 1;

      const rankDiff = releaseRank(a) - releaseRank(b);
      if (rankDiff !== 0) {
        return sort === "release_desc" ? rankDiff : -rankDiff;
      }
      return a.set_code.localeCompare(b.set_code);
    });
  }, [sets, sort, q]);

  const pageSets = displaySets.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  if (error) return <ErrorMessage error={error} onRetry={refetch} />;

  if (isPending) {
    return (
      <div>
        <h1 className="mb-8 text-3xl font-bold text-slate-900 dark:text-slate-50 text-glow">
          JP Pokemon TCG Sets
        </h1>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {Array.from({ length: 15 }).map((_, i) => (
            <SetCardSkeleton key={i} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      <h1 className="mb-8 text-3xl font-bold text-slate-900 dark:text-slate-50 text-glow">
        JP Pokemon TCG Sets
      </h1>
      <SetsFilterBar
        era={era}
        onEraChange={(e) => updateParams({ era: e === "all" ? undefined : e })}
        sort={sort}
        onSortChange={(s) => updateParams({ sort: s === "release_desc" ? undefined : s })}
        searchQuery={localQ}
        onSearchChange={setLocalQ}
        total={displaySets.length}
      />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {pageSets.map((set) => (
          <SetCard key={set.set_code} set={set} />
        ))}
      </div>
      <Pagination
        page={page}
        total={displaySets.length}
        limit={PAGE_SIZE}
        onPageChange={(p) => updateParams({ page: p === 0 ? undefined : p.toString() })}
      />
    </div>
  );
}
