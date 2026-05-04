import type { SpreadRow } from "../../types/api";
import { formatJPY } from "../../lib/formatters";

interface SpreadTableProps {
  rows: SpreadRow[];
}

export function SpreadTable({ rows }: SpreadTableProps) {
  if (rows.length === 0) return null;

  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-slate-800 dark:text-slate-200">
        Cross-source Spread
      </h3>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 dark:border-white/10 text-xs text-slate-500 dark:text-slate-400">
            <th className="pb-2 text-left">Condition</th>
            <th className="pb-2 text-right">CR Floor</th>
            <th className="pb-2 text-right">SD Median 7d</th>
            <th className="pb-2 text-right">Spread</th>
            <th className="pb-2 text-right">Spread %</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.condition} className="border-b border-slate-100 dark:border-white/5 last:border-0 hover:bg-slate-50 dark:hover:bg-white/5 transition-colors">
              <td className="py-2.5 font-medium text-slate-800 dark:text-slate-200">{row.condition}</td>
              <td className="py-2.5 text-right text-slate-700 dark:text-slate-300">
                {formatJPY(row.cardrush_floor)}
              </td>
              <td className="py-2.5 text-right text-slate-700 dark:text-slate-300">
                {formatJPY(Math.round(row.snkrdunk_median_7d))}
              </td>
              <td className="py-2.5 text-right font-medium text-accent-600 dark:text-accent-400">
                {formatJPY(Math.round(row.spread_jpy))}
              </td>
              <td className="py-2.5 text-right text-accent-600 dark:text-accent-400">
                {row.spread_pct != null
                  ? `${row.spread_pct.toFixed(1)}%`
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
