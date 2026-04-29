import { Link } from "react-router";
import { SET_LOGO_URLS } from "../../lib/constants";
import type { SetOut } from "../../types/api";
import { Badge } from "../ui/Badge";

interface SetCardProps {
  set: SetOut;
}

export function SetCard({ set }: SetCardProps) {
  const logoUrl = SET_LOGO_URLS[set.set_code];
  const displayName = set.name_ja ?? set.name_en ?? set.set_code;

  return (
    <Link
      to={`/sets/${set.set_code}`}
      className="flex flex-col rounded-lg border bg-white shadow-sm transition hover:shadow-md overflow-hidden"
    >
      {/* Logo banner */}
      <div className="flex items-center justify-center bg-gray-900 px-4 py-3 min-h-[72px]">
        {logoUrl ? (
          <img
            src={logoUrl}
            alt={displayName}
            className="max-h-12 w-full object-contain"
            onError={(e) => {
              e.currentTarget.style.display = "none";
              e.currentTarget.nextElementSibling?.removeAttribute("hidden");
            }}
          />
        ) : null}
        <span
          hidden={!!logoUrl}
          className="text-sm font-semibold text-white"
        >
          {displayName}
        </span>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between gap-1 px-3 py-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <Badge label={set.set_code} className="shrink-0" />
          {set.name_ja && (
            <span className="truncate text-xs text-gray-500">{set.name_ja}</span>
          )}
        </div>
        <span className="shrink-0 text-xs text-gray-400">
          {set.total != null ? `${set.total}` : ""}
        </span>
      </div>
    </Link>
  );
}
