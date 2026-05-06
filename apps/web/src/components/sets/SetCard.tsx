import { Link } from "react-router";
import { useCurrency } from "../../contexts/CurrencyContext";
import { formatDate } from "../../lib/formatters";
import { SET_LOGO_URLS } from "../../lib/constants";
import type { SetOut } from "../../types/api";
import { SetSymbol } from "../cards/SetSymbol";

interface SetCardProps {
  set: SetOut;
}

export function SetCard({ set }: SetCardProps) {
  const { formatPrice } = useCurrency();
  const codeKey = set.set_code.toUpperCase();
  const logoUrl = SET_LOGO_URLS[codeKey];
  const displayName = set.name_en ?? set.name_ja ?? set.set_code.toLowerCase();

  return (
    <Link
      to={`/sets/${codeKey}`}
      className="flex flex-col glass-panel holo-hover overflow-hidden"
    >
      {/* Logo banner */}
      <div className="flex items-center justify-center bg-slate-50/50 dark:bg-black/40 border-b border-slate-200/50 dark:border-white/5 px-4 py-3 min-h-[72px] relative">
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
          className="text-sm font-semibold text-slate-900 dark:text-white text-glow"
        >
          {displayName}
        </span>
      </div>

      {/* Footer */}
      <div className="space-y-1.5 px-3 py-3">
        <div className="flex items-center justify-between gap-2">
          <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{displayName}</p>
          <SetSymbol
            setCode={set.set_code}
            className="h-4 w-auto max-w-10 shrink-0 object-contain dark:filter dark:invert opacity-80 dark:opacity-80"
          />
        </div>
        <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
          <span>{set.release_date ? formatDate(set.release_date) : "—"}</span>
          <span className="font-semibold text-primary-600 dark:text-primary-400 text-glow">
            {set.total_value_jpy != null ? formatPrice(set.total_value_jpy) : "—"}
          </span>
        </div>
        <p className="text-xs text-slate-500 dark:text-slate-500">{set.total != null ? `${set.total} cards` : ""}</p>
      </div>
    </Link>
  );
}
