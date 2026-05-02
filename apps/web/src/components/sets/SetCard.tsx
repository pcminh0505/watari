import { Link } from "react-router";
import { formatDate, formatJPY } from "../../lib/formatters";
import { SET_LOGO_URLS } from "../../lib/constants";
import type { SetOut } from "../../types/api";
import { SetSymbol } from "../cards/SetSymbol";

interface SetCardProps {
  set: SetOut;
}

export function SetCard({ set }: SetCardProps) {
  const codeKey = set.set_code.toUpperCase();
  const logoUrl = SET_LOGO_URLS[codeKey];
  const displayName = set.name_ja ?? set.name_en ?? set.set_code;

  return (
    <Link
      to={`/sets/${codeKey}`}
      className="flex flex-col rounded-lg border bg-white shadow-sm transition hover:shadow-md overflow-hidden"
    >
      {/* Logo banner */}
      <div className="flex items-center justify-center bg-gray-900 px-4 py-3 min-h-[72px]">
        {logoUrl ? (
          <img
            src={logoUrl}
            alt={displayName}
            className="max-h-12 w-full object-contain"
            referrerPolicy="no-referrer"
            loading="lazy"
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
      <div className="space-y-1.5 px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <p className="truncate text-sm font-semibold text-gray-900">{displayName}</p>
          <SetSymbol
            setCode={set.set_code}
            className="h-4 w-auto max-w-10 shrink-0 object-contain"
          />
        </div>
        <div className="flex items-center justify-between text-xs text-gray-500">
          <span>{set.release_date ? formatDate(set.release_date) : "—"}</span>
          <span className="font-semibold text-blue-600">
            {set.total_value_jpy != null ? formatJPY(set.total_value_jpy) : "—"}
          </span>
        </div>
        <p className="text-xs text-gray-400">{set.total != null ? `${set.total} cards` : ""}</p>
      </div>
    </Link>
  );
}
