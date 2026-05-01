# Historical Price Backfill Strategy + Unified Chart UI

## Context

The app currently shows a two-source price history chart (Cardrush listings as blue line, SNKRDUNK sold as orange line). Two problems exist:

1. **Historical price gap**: For newly onboarded sets, we only have prices from the deployment date forward — no earlier data.
2. **Chart UX**: Showing two separate lines overcomplicates the view. The user wants a single market-price line, with per-source current prices retained in the table below.

The key insight: **SNKRDUNK already stores full sold history with actual transaction dates**. The `observed_at` column for SNKRDUNK rows is the real sale date parsed from the API response (not the scrape timestamp). Cardrush, by contrast, only captures point-in-time listing snapshots. Running the SNKRDUNK scraper on any set immediately yields years of historical price data at no extra engineering cost.

---

## Task 1: Historical Price Backfill Strategy (No Code Changes)

### How It Works Today

`price_points.observed_at` for SNKRDUNK = actual transaction date from the SNKRDUNK sales-history API
`price_points.observed_at` for Cardrush = scrape run timestamp (snapshot only)

The SNKRDUNK scraper (`packages/scraper_snkrdunk/`) already paginates through the full sold history with no date cap. Running it on any set captures all historical transactions.

### Hypothesis (Accepted)

> SNKRDUNK A-condition sold price ≈ Cardrush A-condition listing price ±5%

The cross-source spread MV (`mv_cross_source_spread`) already validates near-parity for A-condition on most SV/ME cards. SNKRDUNK sold = what buyers paid; Cardrush listing = what sellers ask. These track closely in the JP market for A-grade cards. This means the SNKRDUNK sold history is a valid proxy for Cardrush historical prices.

### Backfill Runbook (For Older/New Sets)

```
1. Add to data/sets/*.yml   →  correct set_code + snkrdunk product namespace
2. make catalog-bootstrap SET=<code>
3. make catalog-seed-cards SET=<code>
4. make scrape-snkrdunk SET=<code>   ← pulls ALL historical transactions, no date cap
```

Step 4 alone can yield years of price history. For current SV/ME sets: already done (~104k rows with real sold dates).

**No schema changes, no migrations, no new scrapers needed.**

---

## Task 2: UI Changes — Unified Chart + Table Polish

### 2a. `apps/web/src/components/prices/PriceHistoryChart.tsx`

**Goal**: Single market-price line, no source differentiation.

**Aggregation logic** (replace current `aggregateByDay`):
- Interface: change `DayPoint` from `{ date; cardrush?; snkrdunk? }` → `{ date; price? }`
- Per day: prefer SNKRDUNK sold (actual transaction), fall back to Cardrush listing
  - Points arrive newest-first; first write per source per day wins (keep existing pattern)
  - After collecting both, resolve `price = snkrdunk ?? cardrush`

**Recharts changes**:
- Remove `<Legend />` (no sources to label)
- Replace the two `<Line>` elements with a single one:
  ```tsx
  <Line type="monotone" dataKey="price" stroke="#2563eb" dot={false} connectNulls />
  ```

### 2b. `apps/web/src/components/prices/PriceTable.tsx`

**Goal**: Remove Stock column entirely.

- Delete `hasStock` variable and both conditional `{hasStock && ...}` blocks (header `<th>` + body `<td>`)
- Keep `stock_qty` in the `LatestPrice` type (don't change the API contract)

### 2c. `apps/web/src/lib/formatters.ts`

**Goal**: English-readable date in the "Updated" column.

Change `formatDate` locale from `"ja-JP"` to `"en-US"`:
```typescript
export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
```
Output: `"May 1, 2026"` instead of `"2026年5月1日"`

---

## Critical Files

| File | Change |
|------|--------|
| `apps/web/src/components/prices/PriceHistoryChart.tsx` | Unified single line, new aggregation |
| `apps/web/src/components/prices/PriceTable.tsx` | Remove Stock column |
| `apps/web/src/lib/formatters.ts` | English date format |

No backend changes. No migrations.

---

## Verification

1. `cd apps/web && npm run dev`
2. Navigate to any card detail page (e.g. `/sets/M1L/088`)
3. **Chart**: single blue line, no legend, no two-line split
4. **Latest Prices tables**: no Stock column; dates show "May 1, 2026" style
5. **Stale indicator**: still works — ⚠ still appears for rows older than 14 days (logic unchanged)
6. **Empty state**: still shows "No condition X history available." if no data
