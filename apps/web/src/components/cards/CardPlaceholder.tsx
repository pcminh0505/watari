export function CardPlaceholder() {
  return (
    <div className="flex aspect-[240/336] items-center justify-center rounded-lg bg-gray-100">
      <img
        src="/placeholder-card.svg"
        alt="Card placeholder"
        className="h-full w-full rounded-lg object-cover"
      />
    </div>
  );
}
