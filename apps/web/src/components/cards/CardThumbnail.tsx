import { Link } from "react-router";
import { useMarketPrice } from "../../api/prices";
import { useCurrency } from "../../contexts/CurrencyContext";
import type { ArtworkDetail } from "../../types/api";
import { Badge } from "../ui/Badge";
import { CardPlaceholder } from "./CardPlaceholder";
import { SetSymbol } from "./SetSymbol";

interface CardThumbnailProps {
  card: ArtworkDetail;
}

// Small indicator: sold comp vs. listed price
const SOURCE_LABEL: Record<string, string> = {
  snkrdunk: "sold",
  cardrush: "listed",
};

export function CardThumbnail({ card }: CardThumbnailProps) {
  const displayName = card.name_en ?? card.name_ja ?? card.local_id;
  const variant = card.variants[0]?.variant ?? "normal";
  const { data: market } = useMarketPrice(card.set_code, card.local_id, variant);
  const { formatPrice } = useCurrency();

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
            {card.rarity_code && (
              <Badge label={card.rarity_code} variant="rarity" />
            )}
          </div>
        </div>
      </div>

      {/* English name + price */}
      <div className="px-3 py-3">
        <p className="truncate text-xs font-medium text-slate-800 dark:text-slate-200">
          {card.name_en ?? card.local_id}
        </p>
        {market != null && (
          <div className="mt-1 flex items-baseline gap-1.5">
            <p className="text-sm font-semibold text-primary-600 dark:text-primary-400 text-glow">
              {formatPrice(market.market_price_jpy)}
            </p>
            <span className="text-[9px] text-slate-500 dark:text-slate-500 uppercase tracking-wide">
              {SOURCE_LABEL[market.source_used] ?? market.source_used}
            </span>
          </div>
        )}
      </div>
    </Link>
  );
}
