import clsx from "clsx";

interface SkeletonProps {
  className?: string;
  style?: React.CSSProperties;
}

export function Skeleton({ className, style }: SkeletonProps) {
  return (
    <div
      className={clsx(
        "animate-pulse rounded-md bg-slate-200 dark:bg-slate-800",
        className
      )}
      style={style}
    />
  );
}
