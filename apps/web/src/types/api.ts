/** Mirrors packages/core/watari_core/schemas.py: SetOut */
export interface SetOut {
  set_code: string;
  era_block: string;
  language: string;
  name_ja: string | null;
  name_en: string | null;
  release_date: string | null;
  total: number | null;
  total_value_jpy: number | null;
  parent_set_code: string | null;
  tcgdex_id: string | null;
  source_refs: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** Mirrors packages/api/watari_api/schemas.py: VariantRef */
export interface VariantRef {
  variant: string;
  card_id: string;
  is_tracked: boolean;
}

/** Mirrors packages/api/watari_api/schemas.py: ArtworkDetail */
export interface ArtworkDetail {
  artwork_id: string;
  set_code: string;
  local_id: string;
  language: string;
  name_ja: string | null;
  name_en: string | null;
  rarity_code: string | null;
  image_url: string | null;
  illustrator: string | null;
  category: string;
  variants: VariantRef[];
}

/** Mirrors packages/api/watari_api/schemas.py: ArtworkSearchResult */
export interface ArtworkSearchResult extends ArtworkDetail {
  set_name_ja: string | null;
  set_name_en: string | null;
  set_release_date: string | null;
  cardrush_a_floor_jpy: number | null;
  market_price_jpy: number | null;
  market_price_source_used: "snkrdunk" | "cardrush" | null;
}

/** Mirrors packages/api/watari_api/schemas.py: LatestPrice */
export interface LatestPrice {
  card_id: string;
  source: string;
  condition: string;
  price_jpy: number;
  stock_qty: number | null;
  observed_at: string;
}

/** Mirrors packages/api/watari_api/schemas.py: SpreadRow */
export interface SpreadRow {
  card_id: string;
  condition: string;
  cardrush_floor: number;
  snkrdunk_median_7d: number;
  spread_jpy: number;
  spread_pct: number | null;
}

/** Mirrors packages/core/watari_core/schemas.py: PricePointOut */
export interface PricePointOut {
  id: number;
  card_id: string;
  source: string;
  source_type: string;
  condition: string;
  price_jpy: number;
  stock_qty: number | null;
  observed_at: string;
  external_url: string | null;
  scrape_run_id: number | null;
  created_at: string;
}

/** Mirrors packages/api/watari_api/schemas.py: GradedPricePointOut */
export interface GradedPricePointOut {
  id: number;
  card_id: string;
  source: string;
  source_type: string;
  grade_company: "PSA" | "BGS" | "CGC";
  grade_score: number;
  price_jpy: number;
  observed_at: string;
  external_url: string | null;
}

/** Mirrors packages/api/watari_api/schemas.py: MarketPriceOut */
export interface MarketPriceOut {
  card_id: string;
  market_price_jpy: number;
  source_used: "snkrdunk" | "cardrush";
}

/** Mirrors packages/api/watari_api/schemas.py: InternationalPrice */
export interface InternationalPrice {
  card_id: string;
  market: "tcgplayer" | "cardmarket" | "pricecharting";
  condition_label: string;
  price_jpy: number;
  price_raw: number;
  currency: "USD" | "EUR";
  observed_at: string;
  external_url: string | null;
}

/** Mirrors packages/api/watari_api/schemas.py: ScrapeRunSummary */
export interface ScrapeRunSummary {
  started_at: string | null;
  status: string | null;
  rows_written: number;
  cards_failed: number;
}

/** Mirrors packages/api/watari_api/schemas.py: ScrapeHealthRow */
export interface ScrapeHealthRow {
  set_code: string;
  era_block: string;
  cardrush: ScrapeRunSummary;
  snkrdunk: ScrapeRunSummary;
  warning: "zero_rows" | "consecutive_failures" | "stale_7d" | null;
}
