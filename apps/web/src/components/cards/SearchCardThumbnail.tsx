import { Link } from "react-router";
import { formatJPY } from "../../lib/formatters";
import type { ArtworkSearchResult } from "../../types/api";
import { Badge } from "../ui/Badge";
import { CardPlaceholder } from "./CardPlaceholder";
import { SetSymbol } from "./SetSymbol";

interface SearchCardThumbnailProps {
  card: ArtworkSearchResult;
}

export function SearchCardThumbnail({ card }: SearchCardThumbnailProps) {
  const displayName = card.name_en ?? card.name_ja ?? card.local_id;
  const setName = card.set_name_en ?? card.set_name_ja ?? card.set_code;

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
            <SetSymbol setCode={card.set_code} className="filter invert opacity-90" />
            <span className="text-[10px] text-white/90">{card.local_id}</span>
            {card.rarity_code && <Badge label={card.rarity_code} variant="rarity" />}
          </div>
        </div>
      </div>

      {/* English name + set + price */}
      <div className="px-3 py-3">
        <p className="truncate text-xs font-medium text-neutral-200">{displayName}</p>
        <p className="truncate text-[10px] text-neutral-500">{setName}</p>
        <p className="mt-1 text-sm font-semibold text-primary-400 text-glow">
          {card.cardrush_a_floor_jpy != null ? formatJPY(card.cardrush_a_floor_jpy) : "—"}
        </p>
      </div>
    </Link>
  );
}
