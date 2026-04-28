import {
  CartesianGrid,
  Legend,
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
  cardrush?: number;
  snkrdunk?: number;
}

// Single condition fetched — take the most recent point per source per day.
function aggregateByDay(points: PricePointOut[]): DayPoint[] {
  const dayMap = new Map<string, { cardrush?: number; snkrdunk?: number }>();

  // Points are newest-first from the API; process in order so first write wins.
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
    .map(([date, vals]) => ({ date, ...vals }));
}

export function PriceHistoryChart({ history, condition }: PriceHistoryChartProps) {
  const data = aggregateByDay(history);

  if (data.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        No condition {condition} history available.
      </p>
    );
  }

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} />
          <YAxis
            tickFormatter={(v: number) => `¥${v.toLocaleString("ja-JP")}`}
            tick={{ fontSize: 11 }}
            width={80}
          />
          <Tooltip
            formatter={(value: number) => `¥${value.toLocaleString("ja-JP")}`}
          />
          <Legend />
          <Line
            type="monotone"
            dataKey="cardrush"
            stroke="#2563eb"
            dot={false}
            name="Cardrush"
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="snkrdunk"
            stroke="#ea580c"
            dot={false}
            name="SNKRDUNK"
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
