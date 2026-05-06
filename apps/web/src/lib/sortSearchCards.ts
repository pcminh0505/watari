import type { SortKey } from "../components/cards/CardFilterBar";
import { RARITY_SORT_ORDER } from "./constants";
import type { ArtworkSearchResult } from "../types/api";

function displayPrice(c: ArtworkSearchResult): number | null {
  return c.market_price_jpy ?? c.cardrush_a_floor_jpy ?? null;
}

export function sortSearchCards(cards: ArtworkSearchResult[], sort: SortKey): ArtworkSearchResult[] {
  const rarityOrder = (code: string | null) => RARITY_SORT_ORDER[code ?? ""] ?? 99;

  return [...cards].sort((a, b) => {
    switch (sort) {
      case "number":
        return a.local_id.localeCompare(b.local_id);
      case "name_asc": {
        const na = a.name_en ?? a.name_ja ?? a.local_id;
        const nb = b.name_en ?? b.name_ja ?? b.local_id;
        return na.localeCompare(nb, "en");
      }
      case "name_desc": {
        const na = a.name_en ?? a.name_ja ?? a.local_id;
        const nb = b.name_en ?? b.name_ja ?? b.local_id;
        return nb.localeCompare(na, "en");
      }
      case "rarity_desc":
        return rarityOrder(b.rarity_code) - rarityOrder(a.rarity_code);
      case "rarity_asc":
        return rarityOrder(a.rarity_code) - rarityOrder(b.rarity_code);
      case "price_desc":
        return (displayPrice(b) ?? -1) - (displayPrice(a) ?? -1);
      case "price_asc":
        return (displayPrice(a) ?? Infinity) - (displayPrice(b) ?? Infinity);
    }
  });
}
