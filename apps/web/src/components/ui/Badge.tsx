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

// Per-rarity color overrides used when variant="rarity"
const rarityColors: Record<string, string> = {
  MUR: "bg-gradient-to-r from-pink-500 to-violet-500 text-white",
  UR:  "bg-yellow-400 text-yellow-900",
  SAR: "bg-purple-100 text-purple-800",
  MA:  "bg-purple-100 text-purple-800",
  AR:  "bg-blue-100 text-blue-800",
  SR:  "bg-indigo-100 text-indigo-800",
  RRR: "bg-orange-100 text-orange-800",
  RR:  "bg-orange-100 text-orange-800",
  PR:  "bg-teal-100 text-teal-800",
  R:   "bg-gray-100 text-gray-700",
  U:   "bg-gray-100 text-gray-600",
  C:   "bg-gray-50 text-gray-500",
};

export function Badge({ label, variant = "default", className }: BadgeProps) {
  const colorClass =
    variant === "rarity"
      ? (rarityColors[label] ?? variantClasses.rarity)
      : variantClasses[variant];

  return (
    <span
      className={clsx(
        "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium",
        colorClass,
        className
      )}
    >
      {label}
    </span>
  );
}
