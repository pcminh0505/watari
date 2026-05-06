import { useCurrency } from "../../contexts/CurrencyContext";
import type { LatestPrice } from "../../types/api";

interface PriceTableProps {
  prices: LatestPrice[];
}

const SOURCE_LABELS: Record<string, string> = {
  cardrush: "Cardrush",
  snkrdunk: "SNKRDUNK",
};

export function PriceTable({ prices }: PriceTableProps) {
  const { formatPrice } = useCurrency();
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
            <h4 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-200">
              {SOURCE_LABELS[source] ?? source}
            </h4>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 dark:border-white/10 text-xs text-slate-500 dark:text-slate-400">
                  <th className="pb-2 text-left">Condition</th>
                  <th className="pb-2 text-right">Price</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={`${row.source}-${row.condition}`}
                    className="border-b border-slate-100 dark:border-white/5 last:border-0 hover:bg-slate-50 dark:hover:bg-white/5 transition-colors"
                  >
                    <td className="py-2.5 font-medium text-slate-800 dark:text-slate-200">{row.condition}</td>
                    <td className="py-2.5 text-right font-medium text-primary-600 dark:text-primary-400">
                      {formatPrice(row.price_jpy)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}
