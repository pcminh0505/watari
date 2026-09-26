import { formatDate, formatEUR } from "../../lib/formatters";
import type { EuPrice } from "../../types/api";

const BASIS_LABEL: Record<EuPrice["basis"], string> = {
  normal: "Normal",
  mirror: "Mirror (Poké Ball + Master Ball combined)",
};

function headlineLabel(price: EuPrice): string {
  if (price.trend_eur != null) return "trend";
  if (price.avg30_eur != null) return "30-day avg";
  return "7-day avg";
}

export function EuPriceCard({ price }: { price: EuPrice }) {
  const averages = [
    price.avg7_eur != null ? `7-day avg ${formatEUR(price.avg7_eur)}` : null,
    price.avg30_eur != null ? `30-day avg ${formatEUR(price.avg30_eur)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-bold text-primary-600 dark:text-primary-400 text-glow">
          {formatEUR(price.price_eur)}
        </span>
        <span className="text-xs text-slate-500 dark:text-slate-400">{headlineLabel(price)}</span>
      </div>
      {averages && (
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{averages}</p>
      )}
      <div className="mt-2 flex flex-wrap justify-between gap-2 text-xs text-slate-500 dark:text-slate-400">
        <span>Basis: {BASIS_LABEL[price.basis]}</span>
        <span>Guide: {formatDate(price.guide_date)}</span>
      </div>
      <a
        href={price.url}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-primary-600 hover:underline dark:text-primary-400"
      >
        View JP Near Mint listings on Cardmarket ↗
      </a>
    </div>
  );
}
