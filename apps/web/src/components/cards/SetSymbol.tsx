import { useState } from "react";
import { SET_LOGO_URLS } from "../../lib/constants";

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
  const pokellectorSymbolUrl = SET_LOGO_URLS[code]?.replace(".logo.", ".symbol.");
  const url = pokellectorSymbolUrl;
  const [imageFailed, setImageFailed] = useState(false);
  const imageClassName =
    className ??
    "h-4 max-h-4 w-auto max-w-13 shrink-0 object-contain object-left filter-[drop-shadow(0_1px_1px_rgb(0_0_0/0.85))]";
  const textFallbackClassName = [
    "inline-flex h-4 min-w-7 shrink-0 items-center justify-center rounded-sm border",
    "border-white/80 bg-black/70 px-1 text-[9px] font-black uppercase leading-none",
    "tracking-[0.02em] text-white shadow-[0_1px_1px_rgba(0,0,0,0.75)]",
    className ?? "",
  ]
    .join(" ")
    .trim();

  if (!url || imageFailed) {
    return (
      <span className={textFallbackClassName}>
        {code}
      </span>
    );
  }

  return (
    <img
      src={url}
      alt={`${code.toLowerCase()} symbol`}
      referrerPolicy="no-referrer"
      loading="lazy"
      className={imageClassName}
      onError={() => setImageFailed(true)}
    />
  );
}
