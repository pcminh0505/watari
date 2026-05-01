import { Link } from "react-router";
import { useLatestPrices } from "../../api/prices";
import { formatJPY } from "../../lib/formatters";
import type { ArtworkDetail } from "../../types/api";
import { Badge } from "../ui/Badge";
import { CardPlaceholder } from "./CardPlaceholder";

interface CardThumbnailProps {
  card: ArtworkDetail;
}

export function CardThumbnail({ card }: CardThumbnailProps) {
  const displayName = card.name_ja ?? card.name_en ?? card.local_id;
  const variant = card.variants[0]?.variant ?? "normal";
  const { data: prices } = useLatestPrices(card.set_code, card.local_id, variant);

  const displayPrice = (() => {
    if (!prices || prices.length === 0) return null;
    const crA = prices.find((p) => p.source === "cardrush" && p.condition === "A");
    if (crA) return crA.price_jpy;
    const anyA = prices.find((p) => p.condition === "A");
    if (anyA) return anyA.price_jpy;
    return Math.min(...prices.map((p) => p.price_jpy));
  })();

  return (
    <Link
      to={`/sets/${card.set_code}/${card.local_id}`}
      className="group flex flex-col overflow-hidden rounded-lg border bg-white shadow-sm transition hover:shadow-md"
    >
      {/* Card image with name gradient overlay */}
      <div className="relative">
        {card.image_url ? (
          <img
            src={card.image_url}
            alt={displayName}
            className="aspect-[240/336] w-full object-cover"
            loading="lazy"
          />
        ) : (
          <CardPlaceholder />
        )}
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent px-2 pb-2 pt-8">
          <p className="line-clamp-2 text-xs font-medium leading-tight text-white">
            {displayName}
          </p>
        </div>
      </div>

      {/* Card number + rarity */}
      <div className="flex items-center justify-between px-2 py-1.5 text-xs">
        <span className="text-gray-500">{card.local_id}</span>
        {card.rarity_code && (
          <Badge label={card.rarity_code} variant="rarity" />
        )}
      </div>

      {/* Price */}
      {displayPrice != null && (
        <div className="border-t px-2 pb-2 pt-1">
          <span className="text-sm font-semibold text-blue-600">
            {formatJPY(displayPrice)}
          </span>
        </div>
      )}
    </Link>
  );
}
