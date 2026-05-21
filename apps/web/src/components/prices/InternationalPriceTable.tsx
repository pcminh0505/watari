import { useCurrency } from "../../contexts/CurrencyContext";
import type { InternationalPrice } from "../../types/api";

// Source identity: label, region badge text, left-border + badge colours
const MARKET_CONFIG: Record<string, {
  label: string;
  region: string;
  accentClass: string;
  regionClass: string;
}> = {
  tcgplayer: {
    label: "TCGPlayer",
    region: "US",
    accentClass: "border-l-2 border-blue-400 dark:border-blue-500 pl-3",
    regionClass: "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300",
  },
  cardmarket: {
    label: "Cardmarket",
    region: "EU",
    accentClass: "border-l-2 border-green-400 dark:border-green-500 pl-3",
    regionClass: "bg-green-50 text-green-700 dark:bg-green-950/40 dark:text-green-300",
  },
  pricecharting: {
    label: "PriceCharting",
    region: "eBay",
    accentClass: "border-l-2 border-amber-400 dark:border-amber-500 pl-3",
    regionClass: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300",
  },
};

const MARKET_ORDER = ["tcgplayer", "cardmarket", "pricecharting"];

function formatRaw(price: number, currency: string): string {
  return currency === "EUR" ? `€${price.toFixed(2)}` : `$${price.toFixed(2)}`;
}

function isGraded(row: InternationalPrice): boolean {
  const l = row.condition_label;
  return l.startsWith("PSA") || l.startsWith("BGS") || l.startsWith("CGC");
}

function PriceRow({
  row,
  formatPrice,
}: {
  row: InternationalPrice;
  formatPrice: (jpy: number) => string;
}) {
  return (
    <tr className="border-b border-slate-100 dark:border-white/5 last:border-0 hover:bg-slate-50 dark:hover:bg-white/5 transition-colors">
      <td className="py-2.5 font-medium text-slate-800 dark:text-slate-200">
        {row.condition_label}
      </td>
      <td className="py-2.5 text-right font-medium text-primary-600 dark:text-primary-400">
        {formatPrice(row.price_jpy)}
      </td>
      <td className="py-2.5 text-right text-xs text-slate-400 dark:text-slate-500">
        {formatRaw(row.price_raw, row.currency)}
      </td>
    </tr>
  );
}

function MarketSection({
  market,
  rows,
}: {
  market: string;
  rows: InternationalPrice[];
}) {
  const { formatPrice } = useCurrency();
  const config = MARKET_CONFIG[market] ?? {
    label: market,
    region: "",
    accentClass: "border-l-2 border-slate-300 dark:border-slate-600 pl-3",
    regionClass: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
  };

  // All rows in a market group share the same product URL — put the link on the header.
  const groupUrl = rows.find((r) => r.external_url)?.external_url ?? null;

  // PriceCharting: split raw from graded so graded rows get a sub-section label.
  const rawRows = market === "pricecharting" ? rows.filter((r) => !isGraded(r)) : rows;
  const gradedRows = market === "pricecharting" ? rows.filter((r) => isGraded(r)) : [];

  return (
    <div className={config.accentClass}>
      {/* Source header row */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-slate-800 dark:text-slate-200">
            {config.label}
          </span>
          {config.region && (
            <span
              className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${config.regionClass}`}
            >
              {config.region}
            </span>
          )}
        </div>
        {groupUrl && (
          <a
            href={groupUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-slate-400 hover:text-primary-500 dark:text-slate-500 dark:hover:text-primary-400 transition-colors"
          >
            View ↗
          </a>
        )}
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 dark:border-white/10 text-xs text-slate-500 dark:text-slate-400">
            <th className="pb-2 text-left">Condition</th>
            <th className="pb-2 text-right">Price</th>
            <th className="pb-2 text-right">Original</th>
          </tr>
        </thead>
        <tbody>
          {rawRows.map((row) => (
            <PriceRow key={row.condition_label} row={row} formatPrice={formatPrice} />
          ))}
          {gradedRows.length > 0 && (
            <>
              <tr>
                <td
                  colSpan={3}
                  className="pt-3 pb-1 text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500"
                >
                  Graded
                </td>
              </tr>
              {gradedRows.map((row) => (
                <PriceRow key={row.condition_label} row={row} formatPrice={formatPrice} />
              ))}
            </>
          )}
        </tbody>
      </table>
    </div>
  );
}

export function InternationalPriceTable({ prices }: { prices: InternationalPrice[] }) {
  if (prices.length === 0) return null;

  const byMarket = prices.reduce<Record<string, InternationalPrice[]>>((acc, p) => {
    (acc[p.market] ??= []).push(p);
    return acc;
  }, {});

  const orderedMarkets = [
    ...MARKET_ORDER.filter((m) => m in byMarket),
    ...Object.keys(byMarket).filter((m) => !MARKET_ORDER.includes(m)),
  ];

  return (
    <div>
      <div className="space-y-6">
        {orderedMarkets.map((market) => (
          <MarketSection key={market} market={market} rows={byMarket[market]} />
        ))}
      </div>
      <p className="mt-4 text-xs text-slate-400 dark:text-slate-500">
        Reference prices via{" "}
        <a
          href="https://tcgdex.net"
          target="_blank"
          rel="noopener noreferrer"
          className="hover:underline"
        >
          TCGdex
        </a>{" "}
        ·{" "}
        <a
          href="https://www.pricecharting.com"
          target="_blank"
          rel="noopener noreferrer"
          className="hover:underline"
        >
          PriceCharting
        </a>
        . Converted to JPY using live exchange rates.
      </p>
    </div>
  );
}
