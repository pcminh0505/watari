import type { ArtworkDetail } from "../../types/api";
import { CardThumbnail } from "./CardThumbnail";

interface CardGridProps {
  cards: ArtworkDetail[];
}

export function CardGrid({ cards }: CardGridProps) {
  if (cards.length === 0) {
    return (
      <div className="py-8 text-center">
        <p className="text-sm text-gray-500">No cards found.</p>
        {import.meta.env.DEV && (
          <p className="mt-3 px-4 text-xs text-gray-400">
            If you expect catalog cards here: run the API on{" "}
            <code className="rounded bg-gray-100 px-1 py-0.5">127.0.0.1:8000</code>, set{" "}
            <code className="rounded bg-gray-100 px-1 py-0.5">
              VITE_API_BASE_URL
            </code>{" "}
            in{" "}
            <code className="rounded bg-gray-100 px-1 py-0.5">.env.local</code>, seed the same
            DB (
            <code className="rounded bg-gray-100 px-1 py-0.5">
              make catalog-seed-cards
            </code>
            ), restart Vite, and turn off{" "}
            <strong className="font-medium text-gray-500">Tracked only</strong> if listings
            aren&apos;t scraped yet.
          </p>
        )}
      </div>
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
