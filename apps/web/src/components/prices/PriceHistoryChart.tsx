import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PricePointOut } from "../../types/api";

interface PriceHistoryChartProps {
  history: PricePointOut[];
  condition: string;
}

interface DayPoint {
  date: string;
  price?: number;
}

// Single condition fetched — prefer SNKRDUNK sold (actual transaction), fall back to Cardrush listing.
// Points are newest-first from the API; first write per source per day wins.
function aggregateByDay(points: PricePointOut[]): DayPoint[] {
  const dayMap = new Map<string, { cardrush?: number; snkrdunk?: number }>();

  for (const p of points) {
    const date = p.observed_at.slice(0, 10);
    const existing = dayMap.get(date) ?? {};
    if (p.source === "cardrush" && existing.cardrush == null) {
      existing.cardrush = p.price_jpy;
    } else if (p.source === "snkrdunk" && existing.snkrdunk == null) {
      existing.snkrdunk = p.price_jpy;
    }
    dayMap.set(date, existing);
  }

  return Array.from(dayMap.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, vals]) => ({ date, price: vals.snkrdunk ?? vals.cardrush }));
}

export function PriceHistoryChart({ history, condition }: PriceHistoryChartProps) {
  const data = aggregateByDay(history);

  if (data.length === 0) {
    return (
      <p className="text-sm text-neutral-500">
        No condition {condition} history available.
      </p>
    );
  }

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
          <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#a3a3a3" }} />
          <YAxis
            tickFormatter={(v: number) => `¥${v.toLocaleString("ja-JP")}`}
            tick={{ fontSize: 11, fill: "#a3a3a3" }}
            width={80}
          />
          <Tooltip
            contentStyle={{ backgroundColor: "#0a0a0a", borderColor: "rgba(255,255,255,0.1)", color: "#f5f5f5" }}
            itemStyle={{ color: "#22d3ee" }}
            formatter={(value: number) => `¥${value.toLocaleString("ja-JP")}`}
          />
          <Line type="monotone" dataKey="price" stroke="#22d3ee" strokeWidth={2} dot={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
