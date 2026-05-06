import { Link } from "react-router";
import { useCurrency } from "../../contexts/CurrencyContext";
import type { ArtworkSearchResult } from "../../types/api";
import { Badge } from "../ui/Badge";
import { CardPlaceholder } from "./CardPlaceholder";
import { SetSymbol } from "./SetSymbol";

interface SearchCardThumbnailProps {
  card: ArtworkSearchResult;
}

const SOURCE_LABEL: Record<string, string> = {
  snkrdunk: "sold",
  cardrush: "listed",
};

export function SearchCardThumbnail({ card }: SearchCardThumbnailProps) {
  const { formatPrice } = useCurrency();
  const displayName = card.name_en ?? card.name_ja ?? card.local_id;
  const setName = card.set_name_en ?? card.set_name_ja ?? card.set_code;
  const displayPrice = card.market_price_jpy ?? card.cardrush_a_floor_jpy;
  const source = card.market_price_source_used
    ?? (card.cardrush_a_floor_jpy != null ? "cardrush" : null);

  return (
    <Link
      to={`/sets/${card.set_code}/${card.local_id}`}
      className="group flex flex-col overflow-hidden glass-panel holo-hover"
    >
      {/* Card image */}
      <div className="relative">
        {card.image_url ? (
          <img
            src={card.image_url}
            alt={displayName}
            className="aspect-[240/336] w-full object-cover"
            referrerPolicy="no-referrer"
            loading="lazy"
          />
        ) : (
          <CardPlaceholder />
        )}
        {/* Bottom-left overlay: set code · number · rarity */}
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent px-2 pb-2 pt-8">
          <div className="flex items-center gap-1">
            <SetSymbol setCode={card.set_code} className="dark:filter dark:invert opacity-90 drop-shadow-md" />
            <span className="text-[10px] text-white/90 drop-shadow-md">{card.local_id}</span>
            {card.rarity_code && <Badge label={card.rarity_code} variant="rarity" />}
          </div>
        </div>
      </div>

      {/* English name + set + price */}
      <div className="px-3 py-3">
        <p className="truncate text-xs font-medium text-slate-800 dark:text-slate-200">{displayName}</p>
        <p className="truncate text-[10px] text-slate-500 dark:text-slate-500">{setName}</p>
        <div className="mt-1 flex items-baseline gap-1.5">
          <p className="text-sm font-semibold text-primary-600 dark:text-primary-400 text-glow">
            {displayPrice != null ? formatPrice(displayPrice) : "—"}
          </p>
          {source && (
            <span className="text-[9px] text-slate-500 dark:text-slate-500 uppercase tracking-wide">
              {SOURCE_LABEL[source] ?? source}
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}
