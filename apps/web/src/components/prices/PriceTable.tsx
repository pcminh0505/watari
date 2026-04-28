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
    return <p className="text-sm text-gray-500">No price data available.</p>;
  }

  const bySource = prices.reduce<Record<string, LatestPrice[]>>((acc, p) => {
    (acc[p.source] ??= []).push(p);
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      {Object.entries(bySource).map(([source, rows]) => {
        const hasStock = rows.some((r) => r.stock_qty != null);
        return (
          <div key={source}>
            <h4 className="mb-2 text-sm font-semibold text-gray-700">
              {SOURCE_LABELS[source] ?? source}
            </h4>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-gray-500">
                  <th className="pb-1 text-left">Condition</th>
                  <th className="pb-1 text-right">Price</th>
                  {hasStock && <th className="pb-1 text-right">Stock</th>}
                  <th className="pb-1 text-right">Updated</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const stale = isStale(row.observed_at);
                  return (
                    <tr
                      key={`${row.source}-${row.condition}`}
                      className={`border-b last:border-0 ${stale ? "opacity-50" : ""}`}
                    >
                      <td className="py-1.5 font-medium">{row.condition}</td>
                      <td className="py-1.5 text-right">
                        {formatJPY(row.price_jpy)}
                      </td>
                      {hasStock && (
                        <td className="py-1.5 text-right text-gray-500">
                          {row.stock_qty ?? "—"}
                        </td>
                      )}
                      <td className="py-1.5 text-right text-xs">
                        <span className={stale ? "text-amber-500" : "text-gray-400"}>
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
