import { useMemo } from "react";
import { Link, useParams } from "react-router";
import { useCardSearch } from "../api/cards";
import { PokemonPriceRow } from "../components/pokemon/PokemonPriceRow";
import { ErrorMessage } from "../components/ui/ErrorMessage";
import { Skeleton } from "../components/ui/Skeleton";
import type { ArtworkSearchResult } from "../types/api";

export function PokemonPage() {
  const { name = "" } = useParams<{ name: string }>();

  const { data, isPending, error } = useCardSearch({ q: name, limit: 500 });
  const cards: ArtworkSearchResult[] = data?.data ?? [];

  const grouped = useMemo(() => {
    const map = new Map<string, ArtworkSearchResult[]>();
    for (const card of cards) {
      const existing = map.get(card.set_code) ?? [];
      map.set(card.set_code, [...existing, card]);
    }
    return Array.from(map.entries());
  }, [cards]);

  if (error) return <ErrorMessage error={error} />;

  const totalSets = grouped.length;

  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
        <Link to="/" className="hover:text-slate-900 dark:hover:text-white transition-colors">Sets</Link>
        <span>/</span>
        <span className="text-slate-900 dark:text-slate-50">{name}</span>
      </div>

      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-50 text-glow">{name}</h1>
        {isPending ? (
          <Skeleton className="mt-1 h-4 w-48" />
        ) : (
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {cards.length} card{cards.length !== 1 ? "s" : ""} across {totalSets} set{totalSets !== 1 ? "s" : ""}
          </p>
        )}
      </div>

      {isPending ? (
        <div className="space-y-6">
          {[0, 1, 2].map((i) => (
            <div key={i} className="glass-panel p-5">
              <Skeleton className="mb-4 h-5 w-56" />
              <div className="space-y-3">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
              </div>
            </div>
          ))}
        </div>
      ) : cards.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          No cards found for &ldquo;{name}&rdquo;.
        </p>
      ) : (
        <div className="space-y-8">
          {grouped.map(([setCode, setCards]) => {
            const first = setCards[0];
            const setName = first.set_name_en ?? first.set_name_ja ?? setCode;
            return (
              <section key={setCode} className="glass-panel p-5">
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <Link
                    to={`/sets/${setCode}`}
                    className="text-sm font-semibold text-primary-600 dark:text-primary-400 hover:underline"
                  >
                    {setCode}
                  </Link>
                  <span className="text-slate-300 dark:text-slate-600">·</span>
                  <Link
                    to={`/sets/${setCode}`}
                    className="text-sm text-slate-700 dark:text-slate-300 hover:underline"
                  >
                    {setName}
                  </Link>
                  {first.set_release_date && (
                    <>
                      <span className="text-slate-300 dark:text-slate-600">·</span>
                      <span className="text-xs text-slate-400 dark:text-slate-500">
                        {first.set_release_date.slice(0, 10)}
                      </span>
                    </>
                  )}
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 dark:border-white/10 text-xs text-slate-500 dark:text-slate-400">
                        <th className="pb-2 px-3 text-left font-semibold">#</th>
                        <th className="pb-2 px-3 text-left font-semibold">Name</th>
                        <th className="pb-2 px-3 text-left font-semibold">Rarity</th>
                        <th className="pb-2 px-3 text-left font-semibold">Variant</th>
                        <th className="pb-2 px-3 text-right font-semibold">CR Floor (A)</th>
                        <th className="pb-2 px-3 text-right font-semibold">SD Sold</th>
                        <th className="pb-2 px-3 text-right font-semibold">Market</th>
                      </tr>
                    </thead>
                    <tbody>
                      {setCards.flatMap((card) =>
                        card.variants.map((v, idx) => (
                          <PokemonPriceRow
                            key={`${card.artwork_id}-${v.variant}`}
                            card={card}
                            variant={v.variant}
                            showCardInfo={idx === 0}
                          />
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
