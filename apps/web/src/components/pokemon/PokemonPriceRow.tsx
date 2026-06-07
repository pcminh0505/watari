import { Link } from "react-router";
import { useLatestPrices } from "../../api/prices";
import { useCurrency } from "../../contexts/CurrencyContext";
import type { ArtworkSearchResult } from "../../types/api";
import { Badge } from "../ui/Badge";
import { Skeleton } from "../ui/Skeleton";

interface PokemonPriceRowProps {
  card: ArtworkSearchResult;
  variant: string;
  showCardInfo: boolean;
}

export function PokemonPriceRow({ card, variant, showCardInfo }: PokemonPriceRowProps) {
  const { formatPrice } = useCurrency();
  const { data: prices, isPending } = useLatestPrices(card.set_code, card.local_id, variant);

  const crFloor = prices?.find((p) => p.source === "cardrush" && p.condition === "A")?.price_jpy ?? null;
  const sdSold  = prices?.find((p) => p.source === "snkrdunk" && p.condition === "A")?.price_jpy ?? null;
  const market  = sdSold ?? crFloor ?? null;

  return (
    <tr className="border-b border-slate-100 dark:border-white/5 last:border-0 hover:bg-slate-50 dark:hover:bg-white/5 transition-colors">
      <td className="py-2 px-3 font-mono text-sm text-slate-500 dark:text-slate-400 whitespace-nowrap">
        {showCardInfo ? card.local_id : ""}
      </td>
      <td className="py-2 px-3 text-sm max-w-[180px]">
        {showCardInfo ? (
          <Link
            to={`/sets/${card.set_code}/${card.local_id}`}
            className="font-medium text-primary-600 dark:text-primary-400 hover:underline"
          >
            {card.name_ja ?? card.name_en ?? card.local_id}
          </Link>
        ) : null}
      </td>
      <td className="py-2 px-3 text-sm">
        {showCardInfo && card.rarity_code ? (
          <Badge label={card.rarity_code} variant="rarity" />
        ) : null}
      </td>
      <td className="py-2 px-3 text-xs text-slate-500 dark:text-slate-400 whitespace-nowrap">
        {variant.replace(/_/g, " ")}
      </td>
      <td className="py-2 px-3 text-right text-sm font-medium text-primary-600 dark:text-primary-400">
        {isPending ? (
          <Skeleton className="h-4 w-14 ml-auto" />
        ) : crFloor ? (
          formatPrice(crFloor)
        ) : (
          <span className="text-slate-400 dark:text-slate-600 font-normal">—</span>
        )}
      </td>
      <td className="py-2 px-3 text-right text-sm font-medium text-primary-600 dark:text-primary-400">
        {isPending ? (
          <Skeleton className="h-4 w-14 ml-auto" />
        ) : sdSold ? (
          formatPrice(sdSold)
        ) : (
          <span className="text-slate-400 dark:text-slate-600 font-normal">—</span>
        )}
      </td>
      <td className="py-2 px-3 text-right text-sm font-bold text-slate-900 dark:text-slate-50">
        {isPending ? (
          <Skeleton className="h-4 w-14 ml-auto" />
        ) : market ? (
          formatPrice(market)
        ) : (
          <span className="text-slate-400 dark:text-slate-600 font-normal">—</span>
        )}
      </td>
    </tr>
  );
}
