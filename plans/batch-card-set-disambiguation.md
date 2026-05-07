# Batch Card Lookup — Set Disambiguation Plan

> Status: **proposed** — not yet implemented.
> Tracking issue: `GET /{lang}/cards/batch` currently enforces `set_code local_id`
> and returns `error="missing_set_code"` for bare card-number tokens.
> This document captures the problem and the recommended path to supporting
> denominator-based lookups in the future.

---

## Problem

A physical Pokémon card carries its collector number in the form `066/062`:

- **numerator** (`066`) — the card's position within the set (`local_id` in our DB).
- **denominator** (`062`) — the base-set card count (everything before secret-rares).
  This matches `sets.total` semantically, though `sets.total` is **not yet populated**
  in the DB (the column exists, values are NULL).

When a user scans a card without knowing its set code, they only have
`local_id + denominator`. A bare `066` lookup hits every set that has a card #066
(nearly all 98 sets). Even using `(local_id, denominator)` together there are
**27 denominator collision groups** across our 98 sets where 2–4 sets share the
same base-set size:

| Denominator | Colliding sets | Sets per era |
|---|---|---|
| 63 | M1L, M1S, SV3A, SV9A | ME×2, SV×2 |
| 94 | S11A, S3A, SV6A, SV7A | SW×2, SV×2 |
| 95 | S6H, S6K, SV4K, SV4M | SW×2, SV×2 |
| 250 | M2A, SM8B | ME, SM |
| … | 23 more groups | |

Full collision list (as of 98 sets, derived from artwork counts):

```
 62: SM2K SM2L SM4A SM4S          63: SM5P SM7B
 64: SM3H SM3N                    66: SM2P SM6A
 69: SM10A SM10B SM9B             73: SM1M SM1S SM7A
 75: S1H S1W SM11B                86: S1A S2A SM6B
 88: S10D S10P                    90: S7D S7R
 91: S5I S5R                      92: M1L M1S SV3A SV9A
 93: S10B S9A                     94: S11A S3A SV6A SV7A
 95: S6H S6K SV4K SV4M           96: S5A SV5A
 99: S10A SV2D SV2P              100: SV5K SV5M
108: SV1S SV1V                   115: S2 SM11
116: M2 SM10                     117: M3 SM12
125: S12 SM4P                    127: S11 S9
132: SV10 SV9                    174: SV11B SV11W
250: M2A SM8B
```

---

## Why the current design enforces `set_code`

Cross-era collisions are common. Without the set code, many single-number
lookups would silently return the wrong card or require the caller to handle
a `candidates` list. Requiring `set_code` makes every lookup deterministic.

---

## Proposed future enhancement: denominator + era filtering

### Step 1 — Populate `sets.total`

The `sets.total` column already exists (nullable `integer`). Seed it from:
- **TCGdex** `cardCount.official` (already in our TCGdex client).
- Fallback: count artworks with `local_id <= some_threshold` (rarity-based
  boundary is unreliable; prefer TCGdex).

Run once per set: `make catalog-seed-sets` after updating `_normalize` in
`seed_sets.py` to pull `cardCount.official` into `total`.

### Step 2 — Parse and retain the denominator in `_parse_code_token`

Change the return type to carry the denominator:

```python
def _parse_code_token(raw: str) -> tuple[str | None, str, int | None] | None:
    # returns (set_code, local_id, denominator)
    ...
    denom = int(raw_id_parts[1]) if len(raw_id_parts) == 2 and raw_id_parts[1].isdigit() else None
    return set_code, pad_local_id(raw_id_parts[0]), denom
```

### Step 3 — Denominator-scoped lookup for missing-set-code tokens

When `set_code is None` and `denominator is not None`:

```sql
SELECT <artwork_cols>
FROM artworks
JOIN sets ON sets.set_code = artworks.set_code
WHERE sets.language = :lang
  AND artworks.local_id = :local_id
  AND sets.total = :denominator   -- narrows to sets whose base count matches
```

This resolves the lookup without ambiguity for the **71 denominators** (out of
98) that map to exactly one set.

### Step 4 — Optional era hint to break remaining ties

For the 27 collision groups, allow an optional `era` query parameter
(values: `sv`, `sw`, `sm`, `me`) to scope the lookup to one era block:

```
GET /jp/cards/batch?codes=066/062&era=me
```

Era + denominator eliminates most remaining ambiguity:

| Denominator | All sets | After `era=me` | After `era=sv` |
|---|---|---|---|
| 63 | M1L M1S SV3A SV9A | M1L M1S (still 2) | SV3A SV9A (still 2) |
| 250 | M2A SM8B | M2A ✓ | — |

The two ME sets sharing denominator 63 (M1L / M1S) or SV sets (SV3A / SV9A)
remain collisions. For these, `candidates` must be returned.

### Step 5 — `candidates` fallback for unresolvable ties

If after denominator + era filtering more than one set still matches, return
`error="ambiguous"` with `candidates` populated. The caller can:
1. Show both options to the user (name + set icon).
2. Re-query using the full `set_code local_id` form once the user selects.

---

## Response contract when fully implemented

| `set_code` given | denominator | era | outcome |
|---|---|---|---|
| yes | any | any | precise lookup → `card` or `not_found` |
| no | yes, unique set | any | auto-resolved → `card` or `not_found` |
| no | yes, 2+ sets, era given | narrows to 1 | auto-resolved |
| no | yes, 2+ sets, era doesn't narrow to 1 | any | `ambiguous` + `candidates` |
| no | no / non-numeric | any | `missing_set_code` (current behaviour) |

---

## Work items (ordered)

1. **Seed `sets.total`** from TCGdex `cardCount.official` in `seed_sets._normalize`.
   Verify count against known sets (sv2a=165, m1l=63, sm8b=150).
2. **Extend `_parse_code_token`** to return `denominator` alongside `local_id`.
3. **Add query 2 back** in `get_cards_batch`: denominator-scoped `WHERE sets.total = ?`
   for missing-set-code tokens.
4. **Add `era` query param** (optional) to the batch endpoint; thread it into the
   denominator query as an additional `sets.era_block` filter.
5. **Re-enable `candidates` population** for the remaining ambiguous cases.
6. Update tests + CLAUDE.md.
