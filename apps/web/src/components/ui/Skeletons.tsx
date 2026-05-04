import { Skeleton } from "./Skeleton";

export function TableSkeleton({ columns = 4, rows = 5 }: { columns?: number; rows?: number }) {
  return (
    <div className="w-full rounded-lg border border-slate-200 dark:border-white/10 overflow-hidden bg-white dark:bg-slate-900/50">
      <div className="bg-slate-50 dark:bg-slate-800/50 flex border-b border-slate-200 dark:border-white/10 p-3 gap-4">
        {Array.from({ length: columns }).map((_, i) => (
          <Skeleton key={i} className="h-4 flex-1" />
        ))}
      </div>
      <div className="divide-y divide-slate-100 dark:divide-white/5">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex p-3 gap-4 items-center">
            {Array.from({ length: columns }).map((_, j) => (
              <Skeleton key={j} className="h-4 flex-1" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ChartSkeleton() {
  return (
    <div className="h-[300px] w-full flex items-end gap-2 p-4">
      {Array.from({ length: 12 }).map((_, i) => (
        <Skeleton 
          key={i} 
          className="flex-1 rounded-t-sm" 
          style={{ height: `${Math.max(20, Math.random() * 100)}%` }} 
        />
      ))}
    </div>
  );
}
