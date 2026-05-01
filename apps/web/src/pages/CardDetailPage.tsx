import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { useCard } from "../api/cards";
import { useLatestPrices, usePriceHistory, useSpread } from "../api/prices";
import { CardPlaceholder } from "../components/cards/CardPlaceholder";
import { PriceHistoryChart } from "../components/prices/PriceHistoryChart";
import { PriceTable } from "../components/prices/PriceTable";
import { SpreadTable } from "../components/prices/SpreadTable";
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
      <div className="mb-4 flex items-center gap-2 text-sm text-gray-500">
        <Link to="/" className="hover:text-gray-700">Sets</Link>
        <span>/</span>
        <Link to={`/sets/${setCode}`} className="hover:text-gray-700">{setCode}</Link>
        <span>/</span>
        <span className="text-gray-900">{displayName}</span>
      </div>

      <div className="grid gap-8 lg:grid-cols-[280px_1fr]">
        <div>
          {card.image_url ? (
            <img
              src={card.image_url}
              alt={displayName}
              className="w-full rounded-lg shadow-md"
            />
          ) : (
            <CardPlaceholder />
          )}
          {card.illustrator && (
            <p className="mt-2 text-center text-xs text-gray-400">
              Illus. {card.illustrator}
            </p>
          )}
        </div>

        <div>
          <div className="mb-3 flex flex-wrap items-start gap-2">
            <h1 className="text-2xl font-bold text-gray-900">{displayName}</h1>
            {card.name_ja && card.name_en && (
              <span className="mt-1 text-base text-gray-500">{card.name_en}</span>
            )}
          </div>
          <div className="mb-4 flex flex-wrap gap-2">
            <Badge label={card.set_code} />
            <Badge label={`#${card.local_id}`} />
            {card.rarity_code && (
              <Badge label={card.rarity_code} variant="rarity" />
            )}
          </div>

          {card.variants.length > 1 && (
            <div className="mb-4 flex flex-wrap gap-2">
              {card.variants.map((v) => (
                <button
                  key={v.variant}
                  onClick={() => setSelectedVariant(v.variant)}
                  className={`rounded border px-3 py-1 text-sm transition ${v.variant === variant
                    ? "border-blue-500 bg-blue-50 text-blue-700"
                    : "text-gray-600 hover:border-gray-400"
                    }`}
                >
                  {v.variant.replace(/_/g, " ")}
                </button>
              ))}
            </div>
          )}

          <section className="mb-6">
            <h3 className="mb-2 text-sm font-semibold text-gray-700">
              Latest Prices
            </h3>
            <PriceTable prices={prices ?? []} />
          </section>

          {spread && spread.length > 0 && (
            <section className="mb-6">
              <SpreadTable rows={spread} />
            </section>
          )}

          <section>
            <div className="mb-2 flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-gray-700">
                Price History
              </h3>
              <div className="flex items-center gap-2">
                {/* Period selector */}
                <div className="flex gap-1">
                  {([{ days: 30, label: "30d" }, { days: 60, label: "60d" }, { days: 90, label: "90d" }, { days: 365, label: "1y" }] as const).map(({ days, label }) => (
                    <button
                      key={days}
                      onClick={() => setHistoryDays(days)}
                      className={`rounded border px-2 py-0.5 text-xs transition ${days === historyDays
                        ? "border-blue-500 bg-blue-50 text-blue-700"
                        : "text-gray-500 hover:border-gray-400"
                        }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                {/* Condition selector */}
                {availableConditions.length > 1 && (
                  <div className="flex gap-1">
                    {availableConditions.map((c) => (
                      <button
                        key={c}
                        onClick={() => setHistoryCondition(c)}
                        className={`rounded border px-2 py-0.5 text-xs transition ${c === activeCondition
                          ? "border-blue-500 bg-blue-50 text-blue-700"
                          : "text-gray-500 hover:border-gray-400"
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
