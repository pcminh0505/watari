import { Link } from "react-router";
import { formatJPY } from "../../lib/formatters";
import type { ArtworkSearchResult } from "../../types/api";
import { CardPlaceholder } from "./CardPlaceholder";

interface SearchCardThumbnailProps {
  card: ArtworkSearchResult;
}

export function SearchCardThumbnail({ card }: SearchCardThumbnailProps) {
  const displayName = card.name_ja ?? card.name_en ?? card.local_id;
  const setName = card.set_name_ja ?? card.set_name_en ?? card.set_code;

  return (
    <Link
      to={`/sets/${card.set_code}/${card.local_id}`}
      className="group flex flex-col overflow-hidden rounded-lg border bg-white shadow-sm transition hover:shadow-md"
    >
      <div className="relative">
        {card.image_url ? (
          <img
            src={card.image_url}
            alt={displayName}
            className="aspect-240/336 w-full object-cover"
            loading="lazy"
          />
        ) : (
          <CardPlaceholder />
        )}
        <div className="absolute inset-x-0 bottom-0 bg-linear-to-t from-black/80 to-transparent px-2 pb-2 pt-8">
          <p className="line-clamp-2 text-xs font-medium leading-tight text-white">
            {displayName}
          </p>
        </div>
      </div>

      <div className="space-y-1 px-2 py-2 text-xs">
        <div className="flex items-center justify-between text-gray-600">
          <span>{card.set_code}-{card.local_id}</span>
          <span className="font-bold text-gray-700">{card.rarity_code ?? "-"}</span>
        </div>
        <p className="truncate text-gray-500">{setName}</p>
        <p className="text-sm font-semibold text-blue-600">
          {card.cardrush_a_floor_jpy != null ? formatJPY(card.cardrush_a_floor_jpy) : "—"}
        </p>
      </div>
    </Link>
  );
}
