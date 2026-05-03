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
      className="flex flex-col glass-panel holo-hover overflow-hidden"
    >
      {/* Logo banner */}
      <div className="flex items-center justify-center bg-neutral-950/40 border-b border-white/5 px-4 py-3 min-h-[72px] relative">
        {logoUrl ? (
          <img
            src={logoUrl}
            alt={displayName}
            className="max-h-12 w-full object-contain filter drop-shadow-[0_0_8px_rgba(255,255,255,0.3)]"
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
          className="text-sm font-semibold text-white text-glow"
        >
          {displayName}
        </span>
      </div>

      {/* Footer */}
      <div className="space-y-1.5 px-3 py-3">
        <div className="flex items-center justify-between gap-2">
          <p className="truncate text-sm font-semibold text-neutral-100">{displayName}</p>
          <SetSymbol
            setCode={set.set_code}
            className="h-4 w-auto max-w-10 shrink-0 object-contain filter invert opacity-80"
          />
        </div>
        <div className="flex items-center justify-between text-xs text-neutral-400">
          <span>{set.release_date ? formatDate(set.release_date) : "—"}</span>
          <span className="font-semibold text-primary-400 text-glow">
            {set.total_value_jpy != null ? formatJPY(set.total_value_jpy) : "—"}
          </span>
        </div>
        <p className="text-xs text-neutral-500">{set.total != null ? `${set.total} cards` : ""}</p>
      </div>
    </Link>
  );
}
