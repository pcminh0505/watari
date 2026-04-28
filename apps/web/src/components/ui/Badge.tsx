import clsx from "clsx";

interface BadgeProps {
  label: string;
  variant?: "rarity" | "condition" | "era" | "default";
  className?: string;
}

const variantClasses: Record<NonNullable<BadgeProps["variant"]>, string> = {
  rarity: "bg-yellow-100 text-yellow-800",
  condition: "bg-blue-100 text-blue-800",
  era: "bg-purple-100 text-purple-800",
  default: "bg-gray-100 text-gray-700",
};

export function Badge({ label, variant = "default", className }: BadgeProps) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium",
        variantClasses[variant],
        className
      )}
    >
      {label}
    </span>
  );
}
