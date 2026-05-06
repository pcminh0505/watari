import { Link } from "react-router";
import { useMarketPrice } from "../../api/prices";
import { useCurrency } from "../../contexts/CurrencyContext";
import type { ArtworkDetail, ArtworkSearchResult } from "../../types/api";
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

// Type guard: ArtworkSearchResult extends ArtworkDetail with embedded price fields.
// CardsPage passes search results directly to CardGrid, so we skip individual fetches.
function isSearchResult(card: ArtworkDetail): card is ArtworkSearchResult {
  return "market_price_jpy" in card;
}

export function CardThumbnail({ card }: CardThumbnailProps) {
  const displayName = card.name_en ?? card.name_ja ?? card.local_id;
  const variant = card.variants[0]?.variant ?? "normal";
  const { formatPrice } = useCurrency();

  const hasEmbedded = isSearchResult(card);
  const embeddedMarket =
    hasEmbedded && card.market_price_jpy != null
      ? {
          market_price_jpy: card.market_price_jpy,
          source_used: card.market_price_source_used ?? "cardrush",
        }
      : null;

  // Only fetch individually when the card came without embedded price data.
  const { data: fetchedMarket, isPending } = useMarketPrice(
    card.set_code,
    card.local_id,
    variant,
    !hasEmbedded
  );

  const market = hasEmbedded ? embeddedMarket : fetchedMarket;
  const isLoadingPrice = !hasEmbedded && isPending;

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
        {isLoadingPrice ? (
          <div className="mt-1.5 h-4 w-16 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
        ) : market != null ? (
          <div className="mt-1 flex items-baseline gap-1.5">
            <p className="text-sm font-semibold text-primary-600 dark:text-primary-400 text-glow">
              {formatPrice(market.market_price_jpy)}
            </p>
            <span className="text-[9px] text-slate-500 dark:text-slate-500 uppercase tracking-wide">
              {SOURCE_LABEL[market.source_used] ?? market.source_used}
            </span>
          </div>
        ) : null}
      </div>
    </Link>
  );
}
