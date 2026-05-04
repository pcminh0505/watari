export function CardPlaceholder() {
  return (
    <div className="flex aspect-[240/336] items-center justify-center rounded-lg bg-slate-100 dark:bg-white/5">
      <img
        src="/placeholder-card.svg"
        alt="Card placeholder"
        className="h-full w-full rounded-lg object-cover opacity-30 dark:opacity-30 dark:invert"
      />
    </div>
  );
}
