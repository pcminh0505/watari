import type { SetOut } from "../types/api";
import { SET_LOGO_URLS } from "./constants";

function sourceRefUrl(set: SetOut, key: "logo_url" | "symbol_url"): string | undefined {
  const value = set.source_refs?.[key];
  return typeof value === "string" ? value : undefined;
}

/** Hand-curated logo first, then the TCGCollector logo recorded by `tcgcollector-sync`. */
export function setLogoUrl(set: SetOut): string | undefined {
  return SET_LOGO_URLS[set.set_code.toUpperCase()] ?? sourceRefUrl(set, "logo_url");
}

/** TCGCollector set symbol recorded by `tcgcollector-sync` (fallback for `SetSymbol`). */
export function setSymbolUrl(set: SetOut): string | undefined {
  return sourceRefUrl(set, "symbol_url");
}
