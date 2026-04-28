import type { SpreadRow } from "../../types/api";
import { formatJPY } from "../../lib/formatters";

interface SpreadTableProps {
  rows: SpreadRow[];
}

export function SpreadTable({ rows }: SpreadTableProps) {
  if (rows.length === 0) return null;

  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-gray-700">
        Cross-source Spread
      </h3>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-xs text-gray-500">
            <th className="pb-1 text-left">Condition</th>
            <th className="pb-1 text-right">CR Floor</th>
            <th className="pb-1 text-right">SD Median 7d</th>
            <th className="pb-1 text-right">Spread</th>
            <th className="pb-1 text-right">Spread %</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.condition} className="border-b last:border-0">
              <td className="py-1.5 font-medium">{row.condition}</td>
              <td className="py-1.5 text-right">
                {formatJPY(row.cardrush_floor)}
              </td>
              <td className="py-1.5 text-right">
                {formatJPY(Math.round(row.snkrdunk_median_7d))}
              </td>
              <td className="py-1.5 text-right">
                {formatJPY(Math.round(row.spread_jpy))}
              </td>
              <td className="py-1.5 text-right">
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
