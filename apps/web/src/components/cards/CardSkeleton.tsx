import { Skeleton } from "../ui/Skeleton";

export function CardSkeleton() {
  return (
    <div className="flex flex-col rounded-xl overflow-hidden glass-panel">
      {/* Image placeholder */}
      <div className="aspect-[3/4] w-full p-2 bg-slate-50 dark:bg-black/20">
        <Skeleton className="h-full w-full rounded-lg" />
      </div>
      
      {/* Content */}
      <div className="flex flex-col gap-2 p-3">
        {/* Title */}
        <Skeleton className="h-4 w-3/4" />
        {/* Badges */}
        <div className="flex gap-2">
          <Skeleton className="h-5 w-12 rounded-full" />
          <Skeleton className="h-5 w-10 rounded-full" />
        </div>
        {/* Price & Symbol */}
        <div className="mt-1 flex items-center justify-between">
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-6 rounded-sm" />
        </div>
      </div>
    </div>
  );
}
