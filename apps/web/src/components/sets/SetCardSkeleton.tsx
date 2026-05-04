import { Skeleton } from "../ui/Skeleton";

export function SetCardSkeleton() {
  return (
    <div className="flex flex-col glass-panel overflow-hidden">
      {/* Logo banner area */}
      <div className="flex items-center justify-center bg-slate-50/50 dark:bg-black/40 border-b border-slate-200/50 dark:border-white/5 px-4 py-3 min-h-[72px]">
        <Skeleton className="h-6 w-3/4" />
      </div>

      {/* Footer */}
      <div className="space-y-3 px-3 py-3">
        <div className="flex items-center justify-between gap-2">
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-8" />
        </div>
        <div className="flex items-center justify-between">
          <Skeleton className="h-3 w-1/3" />
          <Skeleton className="h-3 w-1/4" />
        </div>
        <Skeleton className="h-3 w-1/5" />
      </div>
    </div>
  );
}
