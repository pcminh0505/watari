import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { useCard } from "../api/cards";
import { useLatestPrices, usePriceHistory, useSpread } from "../api/prices";
import { CardPlaceholder } from "../components/cards/CardPlaceholder";
import { PriceHistoryChart } from "../components/prices/PriceHistoryChart";
import { PriceTable } from "../components/prices/PriceTable";
import { SpreadTable } from "../components/prices/SpreadTable";
import { SetSymbol } from "../components/cards/SetSymbol";
import { Badge } from "../components/ui/Badge";
import { ErrorMessage } from "../components/ui/ErrorMessage";
import { Spinner } from "../components/ui/Spinner";

export function CardDetailPage() {
  const { setCode = "", localId = "" } = useParams<{
    setCode: string;
    localId: string;
  }>();

  const { data: card, isPending, error } = useCard(setCode, localId);
  const [selectedVariant, setSelectedVariant] = useState<string | null>(null);
  const [historyDays, setHistoryDays] = useState(30);
  const variant = selectedVariant ?? card?.variants[0]?.variant ?? "normal";

  const { data: prices } = useLatestPrices(setCode, localId, variant);
  const { data: spread } = useSpread(setCode, localId, variant);

  // Derive available conditions from the latest prices data.
  // "A-" (Cardrush) is normalized to "B" (SNKRDUNK equivalent).
  const availableConditions = useMemo(() => {
    if (!prices) return ["A"];
    const seen = new Set(prices.map((p) => p.condition));
    const order = ["A", "A-", "B"];
    return order.filter((c) => seen.has(c));
  }, [prices]);

  const [historyCondition, setHistoryCondition] = useState("A");
  // If the card doesn't have condition A, fall back to first available.
  const activeCondition =
    availableConditions.includes(historyCondition)
      ? historyCondition
      : (availableConditions[0] ?? "A");

  const { data: history } = usePriceHistory(
    setCode,
    localId,
    variant,
    historyDays,
    activeCondition
  );
  // When viewing condition "B", also fetch Cardrush "A-" history (they represent
  // the same grade) so the chart merges both sources onto a single line.
  const { data: historyAlt } = usePriceHistory(
    setCode,
    localId,
    variant,
    historyDays,
    "A-",
    activeCondition === "B"
  );
  const chartHistory = useMemo(
    () =>
      activeCondition === "B"
        ? [...(history ?? []), ...(historyAlt ?? [])]
        : (history ?? []),
    [history, historyAlt, activeCondition]
  );

  if (isPending) return <Spinner />;
  if (error || !card) return <ErrorMessage error={error} />;

  const displayName = card.name_ja ?? card.name_en ?? card.local_id;

  return (
    <div>
      <div className="mb-4 flex items-center gap-2 text-sm text-neutral-400">
        <Link to="/" className="hover:text-white transition-colors">Sets</Link>
        <span>/</span>
        <Link to={`/sets/${setCode}`} className="hover:text-white transition-colors">{setCode}</Link>
        <span>/</span>
        <span className="text-neutral-50">{displayName}</span>
      </div>

      <div className="grid gap-8 lg:grid-cols-[280px_1fr]">
        <div>
          {card.image_url ? (
            <img
              src={card.image_url}
              alt={displayName}
              className="w-full rounded-lg shadow-[0_0_15px_rgba(255,255,255,0.1)] border border-white/10"
              referrerPolicy="no-referrer"
            />
          ) : (
            <CardPlaceholder />
          )}
          {card.illustrator && (
            <p className="mt-3 text-center text-xs text-neutral-500">
              Illus. {card.illustrator}
            </p>
          )}
        </div>

        <div>
          <div className="mb-3 flex flex-wrap items-start gap-2">
            <h1 className="text-3xl font-bold text-neutral-50 text-glow">{displayName}</h1>
            {card.name_ja && card.name_en && (
              <span className="mt-2 text-base text-neutral-400">{card.name_en}</span>
            )}
          </div>
          <div className="mb-5 flex flex-wrap items-center gap-2">
            <SetSymbol
              setCode={card.set_code}
              className="h-5 max-h-5 w-auto max-w-16 object-contain filter invert opacity-80"
            />
            <Badge label={card.set_code} />
            <Badge label={`#${card.local_id}`} />
            {card.rarity_code && (
              <Badge label={card.rarity_code} variant="rarity" />
            )}
          </div>

          {card.variants.length > 1 && (
            <div className="mb-6 flex flex-wrap gap-2">
              {card.variants.map((v) => (
                <button
                  key={v.variant}
                  onClick={() => setSelectedVariant(v.variant)}
                  className={`rounded-full border px-4 py-1.5 text-sm font-medium transition-all ${v.variant === variant
                    ? "bg-primary-600/20 text-primary-400 border-primary-500/50 shadow-[0_0_10px_rgba(168,85,247,0.3)]"
                    : "bg-white/5 text-neutral-400 border-white/5 hover:bg-white/10 hover:text-white"
                    }`}
                >
                  {v.variant.replace(/_/g, " ")}
                </button>
              ))}
            </div>
          )}

          <section className="mb-8 glass-panel p-5">
            <h3 className="mb-3 text-sm font-semibold text-neutral-300">
              Latest Prices
            </h3>
            <PriceTable prices={prices ?? []} />
          </section>

          {spread && spread.length > 0 && (
            <section className="mb-8 glass-panel p-5">
              <SpreadTable rows={spread} />
            </section>
          )}

          <section className="glass-panel p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-neutral-300">
                Price History
              </h3>
              <div className="flex items-center gap-2">
                {/* Period selector */}
                <div className="flex gap-1 bg-black/20 p-1 rounded-lg border border-white/5">
                  {([{ days: 30, label: "30d" }, { days: 60, label: "60d" }, { days: 90, label: "90d" }, { days: 365, label: "1y" }] as const).map(({ days, label }) => (
                    <button
                      key={days}
                      onClick={() => setHistoryDays(days)}
                      className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${days === historyDays
                        ? "bg-primary-600/20 text-primary-400 border-primary-500/50"
                        : "bg-transparent text-neutral-400 border-transparent hover:text-white"
                        }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                {/* Condition selector */}
                {availableConditions.length > 1 && (
                  <div className="flex gap-1 bg-black/20 p-1 rounded-lg border border-white/5">
                    {availableConditions.map((c) => (
                      <button
                        key={c}
                        onClick={() => setHistoryCondition(c)}
                        className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${c === activeCondition
                          ? "bg-primary-600/20 text-primary-400 border-primary-500/50"
                          : "bg-transparent text-neutral-400 border-transparent hover:text-white"
                          }`}
                      >
                        {c}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <PriceHistoryChart
              history={chartHistory}
              condition={activeCondition}
            />
          </section>
        </div>
      </div>
    </div>
  );
}
