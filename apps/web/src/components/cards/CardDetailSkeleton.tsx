import { Skeleton } from "../ui/Skeleton";

export function CardDetailSkeleton() {
  return (
    <div className="animate-in fade-in duration-500">
      <div className="mb-4 flex items-center gap-2">
        <Skeleton className="h-5 w-12" />
        <Skeleton className="h-4 w-4" />
        <Skeleton className="h-5 w-24" />
        <Skeleton className="h-4 w-4" />
        <Skeleton className="h-5 w-32" />
      </div>

      <div className="grid gap-8 lg:grid-cols-[280px_1fr]">
        <div>
          <Skeleton className="aspect-[240/336] w-full rounded-lg" />
          <Skeleton className="mt-3 mx-auto h-4 w-1/2" />
        </div>

        <div>
          <div className="mb-3 flex flex-wrap items-start gap-2">
            <Skeleton className="h-10 w-3/4" />
          </div>
          <div className="mb-5 flex flex-wrap items-center gap-2">
            <Skeleton className="h-6 w-16" />
            <Skeleton className="h-6 w-12 rounded-full" />
            <Skeleton className="h-6 w-16 rounded-full" />
          </div>
          
          <Skeleton className="mb-6 h-8 w-40 rounded-full" />

          <div className="mb-8 glass-panel p-5">
            <Skeleton className="mb-3 h-5 w-32" />
            <Skeleton className="h-[200px] w-full rounded-lg" />
          </div>

          <div className="glass-panel p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <Skeleton className="h-5 w-32" />
              <div className="flex gap-2">
                <Skeleton className="h-8 w-32 rounded-lg" />
                <Skeleton className="h-8 w-24 rounded-lg" />
              </div>
            </div>
            <Skeleton className="h-[300px] w-full rounded-lg" />
          </div>
        </div>
      </div>
    </div>
  );
}
