import { useMemo, useState } from "react";
import { useAllSets } from "../api/sets";
import { SetCard } from "../components/sets/SetCard";
import { SetsFilterBar } from "../components/sets/SetsFilterBar";
import { ErrorMessage } from "../components/ui/ErrorMessage";
import { Spinner } from "../components/ui/Spinner";
import { SET_RELEASE_ORDER } from "../lib/constants";
import type { SetOut } from "../types/api";

export function SetsPage() {
  const [era, setEra] = useState<"all" | "sv" | "me" | "sm" | "sw">("all");
  const [sort, setSort] = useState<
    "release_desc" | "release_asc" | "value_desc" | "value_asc"
  >("release_desc");

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
    const items = [...(sets ?? [])];
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
  }, [sets, sort]);

  if (isPending) return <Spinner />;
  if (error) return <ErrorMessage error={error} onRetry={refetch} />;

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold text-gray-900">
        JP Pokemon TCG Sets
      </h1>
      <SetsFilterBar
        era={era}
        onEraChange={setEra}
        sort={sort}
        onSortChange={setSort}
        total={displaySets.length}
      />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {displaySets.map((set) => (
          <SetCard key={set.set_code} set={set} />
        ))}
      </div>
    </div>
  );
}
