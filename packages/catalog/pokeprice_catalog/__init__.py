"""PokePrice Catalog — catalog metadata build pipeline.

Three-stage pipeline:
    seed-sets       -> upsert Set rows from sets.yml
    enrich-tcgdex   -> upsert Card rows from TCGdex per-card API
    discover-cardrush -> augment with Japanese names / rarities / variants / new sets

Run with: ``python -m pokeprice_catalog <command>``.
"""
