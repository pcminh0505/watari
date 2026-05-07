import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useMemo } from "react";
import { useCurrency } from "../../contexts/CurrencyContext";
import type { GradedPricePointOut } from "../../types/api";

const SUPPORTED_GRADES = [
  { key: "PSA_10", company: "PSA", score: 10, label: "PSA 10", color: "#0ea5e9" },
  { key: "PSA_9", company: "PSA", score: 9, label: "PSA 9", color: "#2563eb" },
  { key: "PSA_8", company: "PSA", score: 8, label: "PSA 8", color: "#1d4ed8" },
  { key: "BGS_10", company: "BGS", score: 10, label: "BGS 10", color: "#14b8a6" },
  { key: "BGS_9_5", company: "BGS", score: 9.5, label: "BGS 9.5", color: "#0f766e" },
] as const;

type GradeKey = (typeof SUPPORTED_GRADES)[number]["key"];

type DayPoint = {
  date: string;
} & Partial<Record<GradeKey, number>>;

function gradeKey(point: GradedPricePointOut): GradeKey | null {
  const grade = SUPPORTED_GRADES.find(
    (g) => g.company === point.grade_company && g.score === point.grade_score
  );
  return grade?.key ?? null;
}

// The API returns newest-first. For each grade/day, prefer SNKRDUNK sold comps
// over Cardrush listings so the line reflects actual transactions when present.
function aggregateByDay(points: GradedPricePointOut[]): DayPoint[] {
  const dayMap = new Map<
    string,
    Partial<Record<GradeKey, { cardrush?: number; snkrdunk?: number }>>
  >();

  for (const point of points) {
    const key = gradeKey(point);
    if (key == null) continue;

    const date = point.observed_at.slice(0, 10);
    const existingDay = dayMap.get(date) ?? {};
    const existingGrade = existingDay[key] ?? {};

    if (point.source === "snkrdunk" && existingGrade.snkrdunk == null) {
      existingGrade.snkrdunk = point.price_jpy;
    } else if (point.source === "cardrush" && existingGrade.cardrush == null) {
      existingGrade.cardrush = point.price_jpy;
    }

    existingDay[key] = existingGrade;
    dayMap.set(date, existingDay);
  }

  return Array.from(dayMap.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, grades]) => {
      const row: DayPoint = { date };
      for (const grade of SUPPORTED_GRADES) {
        const value = grades[grade.key];
        row[grade.key] = value?.snkrdunk ?? value?.cardrush;
      }
      return row;
    });
}

function latestValue(data: DayPoint[], key: GradeKey): number | undefined {
  for (let i = data.length - 1; i >= 0; i -= 1) {
    if (data[i][key] != null) return data[i][key];
  }
  return undefined;
}

export function GradedPriceHistoryChart({
  history,
}: {
  history: GradedPricePointOut[];
}) {
  const { formatPrice } = useCurrency();
  const data = useMemo(() => aggregateByDay(history), [history]);
  const activeGrades = useMemo(
    () =>
      SUPPORTED_GRADES.map((grade) => ({
        ...grade,
        latest: latestValue(data, grade.key),
      })).filter((grade) => grade.latest != null),
    [data]
  );

  if (activeGrades.length === 0) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        No PSA 10/9/8 or BGS 10/9.5 history available.
      </p>
    );
  }

  return (
    <div>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-chart-grid)" />
            <XAxis dataKey="date" tick={{ fontSize: 11, fill: "var(--color-chart-text)" }} />
            <YAxis
              tickFormatter={(v: number) => formatPrice(v)}
              tick={{ fontSize: 11, fill: "var(--color-chart-text)" }}
              width={80}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--color-chart-tooltip-bg)",
                borderColor: "var(--color-chart-tooltip-border)",
                color: "var(--color-chart-tooltip-text)",
              }}
              formatter={(value: number, name: string) => [formatPrice(value), name]}
            />
            {activeGrades.map((grade) => (
              <Line
                key={grade.key}
                type="monotone"
                dataKey={grade.key}
                name={grade.label}
                stroke={grade.color}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {activeGrades.map((grade) => (
          <div key={grade.key} className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
            <span className="h-3 w-3 rounded-sm" style={{ backgroundColor: grade.color }} />
            <span>{grade.label}</span>
            <span className="text-slate-400 dark:text-slate-500">
              ({formatPrice(grade.latest ?? 0)})
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
