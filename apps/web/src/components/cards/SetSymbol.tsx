import { SET_SYMBOL_URLS } from "../../lib/constants";

interface SetSymbolProps {
  /** Set code as returned by the API (any casing). */
  setCode: string;
  className?: string;
}

/**
 * Small TCG set-symbol image (Bulbagarden Archives). Only renders when
 * `SET_SYMBOL_URLS` has an entry — extend the map per set as needed.
 */
export function SetSymbol({ setCode, className }: SetSymbolProps) {
  const code = setCode.toUpperCase();
  const url = SET_SYMBOL_URLS[code];
  if (!url) return null;

  return (
    <img
      src={url}
      alt={`${code.toLowerCase()} symbol`}
      referrerPolicy="no-referrer"
      loading="lazy"
      className={
        className ??
        "h-4 max-h-4 w-auto max-w-13 shrink-0 object-contain object-left filter-[drop-shadow(0_1px_1px_rgb(0_0_0/0.85))]"
      }
      onError={(e) => {
        e.currentTarget.style.display = "none";
      }}
    />
  );
}
