import { useState } from "react";
import { useScrapeHealth } from "../api/admin";
import type { ScrapeHealthRow, ScrapeRunSummary } from "../types/api";

const ERA_LABELS: Record<string, string> = {
  sv: "SV",
  me: "ME",
  sm: "SM",
  sw: "SW",
};

const WARNING_BADGE: Record<string, { label: string; cls: string }> = {
  consecutive_failures: { label: "failures", cls: "bg-red-100 text-red-700" },
  zero_rows: { label: "zero rows", cls: "bg-yellow-100 text-yellow-700" },
  stale_7d: { label: "stale 7d", cls: "bg-orange-100 text-orange-700" },
};

function RunCell({ run }: { run: ScrapeRunSummary }) {
  if (run.started_at == null) {
    return <span className="text-gray-300 text-xs">—</span>;
  }
  const date = new Date(run.started_at).toLocaleDateString("ja-JP", {
    month: "2-digit",
    day: "2-digit",
  });
  const statusCls =
    run.status === "ok"
      ? "text-green-600"
      : run.status === "error"
        ? "text-red-600"
        : "text-gray-500";
  return (
    <div className="text-xs">
      <span className={`font-medium ${statusCls}`}>{run.status ?? "?"}</span>
      <span className="mx-1 text-gray-300">·</span>
      <span className="text-gray-600">{run.rows_written.toLocaleString()} rows</span>
      {run.cards_failed > 0 && (
        <span className="ml-1 text-red-500">({run.cards_failed} failed)</span>
      )}
      <div className="text-gray-400">{date}</div>
    </div>
  );
}

function WarningBadge({ warning }: { warning: ScrapeHealthRow["warning"] }) {
  if (!warning) return null;
  const cfg = WARNING_BADGE[warning];
  if (!cfg) return null;
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${cfg.cls}`}>
      {cfg.label}
    </span>
  );
}

export function AdminPage() {
  const [era, setEra] = useState<string>("all");
  const { data: rows, isPending, error, refetch } = useScrapeHealth();

  const eras = ["all", "sv", "me", "sm", "sw"];
  const filtered =
    era === "all" ? (rows ?? []) : (rows ?? []).filter((r) => r.era_block === era);

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">Scrape Health</h1>
        <button
          onClick={() => refetch()}
          className="rounded border px-3 py-1 text-sm text-gray-600 hover:bg-gray-50"
        >
          Refresh
        </button>
      </div>

      {/* Era filter pills */}
      <div className="mb-4 flex gap-2">
        {eras.map((e) => (
          <button
            key={e}
            onClick={() => setEra(e)}
            className={`rounded-full px-3 py-1 text-sm font-medium transition ${
              era === e
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {e === "all" ? "All" : ERA_LABELS[e] ?? e.toUpperCase()}
          </button>
        ))}
      </div>

      {isPending && (
        <p className="text-sm text-gray-500">Loading scrape health…</p>
      )}
      {error && (
        <p className="text-sm text-red-600">
          Failed to load: {(error as Error).message}
        </p>
      )}

      {!isPending && !error && (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-3 py-2">Set</th>
                <th className="px-3 py-2">Era</th>
                <th className="px-3 py-2">Cardrush</th>
                <th className="px-3 py-2">SNKRDUNK</th>
                <th className="px-3 py-2">Warning</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map((row) => (
                <tr
                  key={row.set_code}
                  className={
                    row.warning === "consecutive_failures"
                      ? "bg-red-50"
                      : row.warning === "zero_rows"
                        ? "bg-yellow-50"
                        : row.warning === "stale_7d"
                          ? "bg-orange-50"
                          : ""
                  }
                >
                  <td className="px-3 py-2 font-mono font-medium text-gray-800">
                    {row.set_code}
                  </td>
                  <td className="px-3 py-2 text-gray-500">{row.era_block.toUpperCase()}</td>
                  <td className="px-3 py-2">
                    <RunCell run={row.cardrush} />
                  </td>
                  <td className="px-3 py-2">
                    <RunCell run={row.snkrdunk} />
                  </td>
                  <td className="px-3 py-2">
                    <WarningBadge warning={row.warning} />
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-gray-400">
                    No sets found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-3 text-xs text-gray-400">
        Internal dashboard. Data refreshes from DB on each page load.
      </p>
    </div>
  );
}
