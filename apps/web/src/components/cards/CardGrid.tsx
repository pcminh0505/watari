import type { ArtworkDetail } from "../../types/api";
import { CardThumbnail } from "./CardThumbnail";

interface CardGridProps {
  cards: ArtworkDetail[];
}

export function CardGrid({ cards }: CardGridProps) {
  if (cards.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-gray-500">No cards found.</p>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
      {cards.map((card) => (
        <CardThumbnail key={card.artwork_id} card={card} />
      ))}
    </div>
  );
}
