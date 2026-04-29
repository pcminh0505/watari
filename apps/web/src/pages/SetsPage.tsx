import { useMemo } from "react";
import { useAllSets } from "../api/sets";
import { EraSection } from "../components/sets/EraSection";
import { ErrorMessage } from "../components/ui/ErrorMessage";
import { Spinner } from "../components/ui/Spinner";
import { ERA_LABELS, SET_RELEASE_ORDER } from "../lib/constants";
import type { SetOut } from "../types/api";

export function SetsPage() {
  const { data: sets, isPending, error, refetch } = useAllSets();

  const grouped = useMemo(() => {
    if (!sets) return [];
    const map = new Map<string, SetOut[]>();
    for (const set of sets) {
      const list = map.get(set.era_block) ?? [];
      list.push(set);
      map.set(set.era_block, list);
    }
    const ERA_ORDER: Record<string, number> = { sv: 0, me: 1 };
    return Array.from(map.entries())
      .sort(([a], [b]) => (ERA_ORDER[a] ?? 99) - (ERA_ORDER[b] ?? 99))
      .map(([era, eraSets]) => [
        era,
        [...eraSets].sort(
          (a, b) =>
            (SET_RELEASE_ORDER[a.set_code] ?? 999) -
            (SET_RELEASE_ORDER[b.set_code] ?? 999)
        ),
      ] as [string, SetOut[]]);
  }, [sets]);

  if (isPending) return <Spinner />;
  if (error) return <ErrorMessage error={error} onRetry={refetch} />;

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold text-gray-900">
        JP Pokemon TCG Sets
      </h1>
      {grouped.map(([era, eraSets]) => (
        <EraSection
          key={era}
          label={ERA_LABELS[era] ?? era.toUpperCase()}
          sets={eraSets}
        />
      ))}
    </div>
  );
}
