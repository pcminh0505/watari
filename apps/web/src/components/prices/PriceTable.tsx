import type { LatestPrice } from "../../types/api";
import { formatDate, formatJPY } from "../../lib/formatters";

const STALE_DAYS = 14;

function isStale(observedAt: string): boolean {
  return (
    (Date.now() - new Date(observedAt).getTime()) / 86_400_000 > STALE_DAYS
  );
}

interface PriceTableProps {
  prices: LatestPrice[];
}

const SOURCE_LABELS: Record<string, string> = {
  cardrush: "Cardrush",
  snkrdunk: "SNKRDUNK",
};

export function PriceTable({ prices }: PriceTableProps) {
  if (prices.length === 0) {
    return <p className="text-sm text-neutral-500">No price data available.</p>;
  }

  const bySource = prices.reduce<Record<string, LatestPrice[]>>((acc, p) => {
    (acc[p.source] ??= []).push(p);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      {Object.entries(bySource).map(([source, rows]) => {
        return (
          <div key={source}>
            <h4 className="mb-3 text-sm font-semibold text-neutral-300">
              {SOURCE_LABELS[source] ?? source}
            </h4>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 text-xs text-neutral-500">
                  <th className="pb-2 text-left">Condition</th>
                  <th className="pb-2 text-right">Price</th>
                  <th className="pb-2 text-right">Updated</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const stale = isStale(row.observed_at);
                  return (
                    <tr
                      key={`${row.source}-${row.condition}`}
                      className={`border-b border-white/5 last:border-0 hover:bg-white/5 transition-colors ${stale ? "opacity-50" : ""}`}
                    >
                      <td className="py-2.5 font-medium text-neutral-200">{row.condition}</td>
                      <td className="py-2.5 text-right font-medium text-primary-400">
                        {formatJPY(row.price_jpy)}
                      </td>
                      <td className="py-2.5 text-right text-xs">
                        <span className={stale ? "text-amber-400" : "text-neutral-500"}>
                          {formatDate(row.observed_at)}
                          {stale && " ⚠"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}
