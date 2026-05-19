import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { useCard } from "../api/cards";
import { useSet } from "../api/sets";
import { useGradedPriceHistory, useLatestPrices, usePriceHistory, useSpread } from "../api/prices";
import { CardPlaceholder } from "../components/cards/CardPlaceholder";
import { CardDetailSkeleton } from "../components/cards/CardDetailSkeleton";
import { GradedPriceHistoryChart } from "../components/prices/GradedPriceHistoryChart";
import { PriceHistoryChart } from "../components/prices/PriceHistoryChart";
import { PriceTable } from "../components/prices/PriceTable";
import { SpreadTable } from "../components/prices/SpreadTable";
import { SetSymbol } from "../components/cards/SetSymbol";
import { Badge } from "../components/ui/Badge";
import { ErrorMessage } from "../components/ui/ErrorMessage";
import { ChartSkeleton, TableSkeleton } from "../components/ui/Skeletons";

export function CardDetailPage() {
  const { setCode = "", localId = "" } = useParams<{
    setCode: string;
    localId: string;
  }>();

  const { data: card, isPending, error } = useCard(setCode, localId);
  const { data: set } = useSet(setCode);
  const [selectedVariant, setSelectedVariant] = useState<string | null>(null);
  const [historyDays, setHistoryDays] = useState(30);
  const [gradedHistoryDays, setGradedHistoryDays] = useState(90);
  const variant = selectedVariant ?? card?.variants[0]?.variant ?? "normal";

  const { data: prices, isPending: isPricesPending } = useLatestPrices(setCode, localId, variant);
  const { data: spread, isPending: isSpreadPending } = useSpread(setCode, localId, variant);

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

  const { data: history, isPending: isHistoryPending } = usePriceHistory(
    setCode,
    localId,
    variant,
    historyDays,
    activeCondition
  );
  // When viewing condition "B", also fetch Cardrush "A-" history (they represent
  // the same grade) so the chart merges both sources onto a single line.
  const { data: historyAlt, isPending: isHistoryAltPending } = usePriceHistory(
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
  const { data: gradedHistory, isPending: isGradedHistoryPending } = useGradedPriceHistory(
    setCode,
    localId,
    variant,
    gradedHistoryDays
  );

  if (isPending) return <CardDetailSkeleton />;
  if (error || !card) return <ErrorMessage error={error} />;

  const displayName = card.name_en ?? card.name_ja ?? card.local_id;
  const setName = set ? (set.name_en ?? set.name_ja ?? setCode.toLowerCase()) : setCode.toLowerCase();

  return (
    <div>
      <div className="mb-4 flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
        <Link to="/" className="hover:text-slate-900 dark:hover:text-white transition-colors">Sets</Link>
        <span>/</span>
        <Link to={`/sets/${setCode}`} className="hover:text-slate-900 dark:hover:text-white transition-colors">{setName}</Link>
        <span>/</span>
        <span className="text-slate-900 dark:text-slate-50">{displayName}</span>
      </div>

      <div className="grid gap-8 lg:grid-cols-[280px_1fr]">
        <div>
          {card.image_url ? (
            <img
              src={card.image_url}
              alt={displayName}
              className="w-full rounded-lg shadow-sm dark:shadow-[0_0_15px_rgba(255,255,255,0.1)] border border-slate-200 dark:border-white/10"
              referrerPolicy="no-referrer"
            />
          ) : (
            <CardPlaceholder />
          )}
          {card.illustrator && (
            <p className="mt-3 text-center text-xs text-slate-500">
              Illus.{" "}
              <Link
                to={`/cards?illustrator=${encodeURIComponent(card.illustrator)}`}
                className="hover:text-primary-500 dark:hover:text-primary-400 hover:underline transition-colors"
              >
                {card.illustrator}
              </Link>
            </p>
          )}
        </div>

        <div>
          <div className="mb-3 flex flex-wrap items-start gap-2">
            <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-50 text-glow">{displayName}</h1>
            {card.name_ja && card.name_en && (
              <span className="mt-2 text-base text-slate-500 dark:text-slate-400">{card.name_en}</span>
            )}
          </div>
          <div className="mb-5 flex flex-wrap items-center gap-2">
            <SetSymbol
              setCode={card.set_code}
              className="h-5 max-h-5 w-auto max-w-16 object-contain dark:filter dark:invert dark:opacity-80 drop-shadow-sm"
            />
            <Badge label={card.set_code.toLowerCase()} />
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
                    ? "bg-primary-50 text-primary-700 border-primary-500 dark:bg-primary-900/40 dark:text-primary-300 dark:border-primary-500/50 shadow-sm dark:shadow-[0_0_10px_rgba(14,165,233,0.3)]"
                    : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50 hover:text-slate-900 dark:bg-white/5 dark:text-slate-400 dark:border-white/5 dark:hover:bg-white/10 dark:hover:text-white"
                    }`}
                >
                  {v.variant.replace(/_/g, " ")}
                </button>
              ))}
            </div>
          )}

          <section className="mb-8 glass-panel p-5">
            <h3 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-200">
              Latest Prices
            </h3>
            {isPricesPending ? <TableSkeleton columns={5} rows={3} /> : <PriceTable prices={prices ?? []} />}
          </section>

          {isSpreadPending ? (
            <section className="mb-8 glass-panel p-5">
               <TableSkeleton columns={6} rows={1} />
            </section>
          ) : spread && spread.length > 0 ? (
            <section className="mb-8 glass-panel p-5">
              <SpreadTable rows={spread} />
            </section>
          ) : null}

          <section className="glass-panel p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                Ungraded Price History
              </h3>
              <div className="flex items-center gap-2">
                {/* Period selector */}
                <div className="flex gap-1 bg-slate-100 dark:bg-black/20 p-1 rounded-lg border border-slate-200 dark:border-white/5">
                  {([{ days: 30, label: "30d" }, { days: 60, label: "60d" }, { days: 90, label: "90d" }] as const).map(({ days, label }) => (
                    <button
                      key={days}
                      onClick={() => setHistoryDays(days)}
                      className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${days === historyDays
                        ? "bg-white text-primary-600 border-slate-200 shadow-sm dark:bg-primary-900/40 dark:text-primary-300 dark:border-primary-500/50"
                        : "bg-transparent text-slate-500 border-transparent hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                        }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                {/* Condition selector */}
                {availableConditions.length > 1 && (
                  <div className="flex gap-1 bg-slate-100 dark:bg-black/20 p-1 rounded-lg border border-slate-200 dark:border-white/5">
                    {availableConditions.map((c) => (
                      <button
                        key={c}
                        onClick={() => setHistoryCondition(c)}
                        className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${c === activeCondition
                          ? "bg-white text-primary-600 border-slate-200 shadow-sm dark:bg-primary-900/40 dark:text-primary-300 dark:border-primary-500/50"
                          : "bg-transparent text-slate-500 border-transparent hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                          }`}
                      >
                        {c}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            {isHistoryPending || (activeCondition === "B" && isHistoryAltPending) ? (
              <ChartSkeleton />
            ) : (
              <PriceHistoryChart
                history={chartHistory}
                condition={activeCondition}
              />
            )}
          </section>

          <section className="mt-8 glass-panel p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                Graded Price History
              </h3>
              <div className="flex gap-1 bg-slate-100 dark:bg-black/20 p-1 rounded-lg border border-slate-200 dark:border-white/5">
                {([{ days: 30, label: "1M" }, { days: 90, label: "3M" }] as const).map(({ days, label }) => (
                  <button
                    key={days}
                    onClick={() => setGradedHistoryDays(days)}
                    aria-pressed={days === gradedHistoryDays}
                    className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${days === gradedHistoryDays
                      ? "bg-white text-primary-600 border-slate-200 shadow-sm dark:bg-primary-900/40 dark:text-primary-300 dark:border-primary-500/50"
                      : "bg-transparent text-slate-500 border-transparent hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                      }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            {isGradedHistoryPending ? (
              <ChartSkeleton />
            ) : (
              <GradedPriceHistoryChart history={gradedHistory ?? []} />
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
