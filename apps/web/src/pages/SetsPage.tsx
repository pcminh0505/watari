import { useMemo } from "react";
import { useAllSets } from "../api/sets";
import { EraSection } from "../components/sets/EraSection";
import { ErrorMessage } from "../components/ui/ErrorMessage";
import { Spinner } from "../components/ui/Spinner";
import { ERA_LABELS } from "../lib/constants";
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
    return Array.from(map.entries()).sort(
      ([a], [b]) => (ERA_ORDER[a] ?? 99) - (ERA_ORDER[b] ?? 99)
    );
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
