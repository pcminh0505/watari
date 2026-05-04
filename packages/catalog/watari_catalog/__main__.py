"""CLI: ``python -m watari_catalog <command> [options]``.

Commands (v3 pipeline):

    seed-sets
        Upsert ``Set`` rows from ``data/sets/*.yml``.

    bootstrap-set --set SV2A [--set M2A] [--no-fetch]
        Build / refresh the per-card YML tree for a set from Pokellector
        (primary), TCGdex (fallback), and Cardrush (variant hints).
        Writes ``data/cards/{set_code}/{local_id}.yml`` preserving the
        ``# manual: true`` opt-out on existing files.

    seed-cards [--set SV2A]
        Load the YML tree into ``artworks`` and ``cards`` tables.

    verify [--strict]
        Print a catalog health snapshot. ``--strict`` exits non-zero if any
        non-promo set has nulls in ``name_ja`` / ``rarity_code``.

    verify-pokellector [--set SV2A ...]
        Compare ``data/cards/{SET}/*.yml`` local_ids to the live set index on
        https://jp.pokellector.com/ (requires network).

    audit-current [--set SV2A]
        Walk the YML tree and write a per-set Markdown report with field-
        level gaps (null name_ja/name_en/rarity/illustrator, plus cross-
        source rarity disagreements). No data changes.

    audit-fetch --set SV2A
        Scrape TCGCollector for one set (uses the ``tcgcollector_slug``
        recorded in ``data/sets/<SET>.yml``) and write the sidecar oracle
        file ``data/audit/<SET>.yml``.

    audit-diff [--set SV2A]
        Diff ``data/audit/*.yml`` (oracle) against ``data/cards/**`` (current
        truth) and emit ``reports/audit-diff-<utc>.md`` + ``.tsv`` with
        AUTO_FILL / MATCH / CONFLICT / NO_ORACLE classifications.

    audit-fallback --set SV2A --field name_ja|name_en|illustrator
        For CONFLICT/NO_ORACLE rows from ``audit-diff``, hit the fallback
        oracle (pokemon-card.com for name_ja, Bulbapedia for name_en /
        illustrator) and append the answers into ``data/audit/<SET>.yml``.

    audit-apply --tsv reports/audit-diff-...tsv [--auto | --review]
        Apply the chosen oracle values to ``data/cards/<SET>/<NNN>.yml``.
        ``--auto`` writes only AUTO_FILL rows; ``--review`` writes the
        operator-edited TSV and prepends ``# manual: true`` to each file.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("watari_catalog")
    p.add_argument("--log-level", default="INFO")

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("seed-sets", help="Upsert Set rows from data/sets/*.yml")

    b = sub.add_parser(
        "bootstrap-set",
        help="Build data/cards/{set_code}/*.yml from Pokellector + TCGdex + Cardrush",
    )
    b.add_argument("--set", dest="sets", action="append", required=True)
    b.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip network calls; rebuild from MinIO bronze cache only",
    )

    s = sub.add_parser(
        "seed-cards",
        help="Load data/cards/*/*.yml into artworks/cards tables",
    )
    s.add_argument("--set", dest="sets", action="append", default=None)

    v = sub.add_parser("verify", help="Print catalog health snapshot")
    v.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit non-zero if any non-promo set has nulls in name_ja or "
            "rarity_code (lacks the `# explicit-no-ja: true` marker)."
        ),
    )

    vp = sub.add_parser(
        "verify-pokellector",
        help="Cross-check card YML numbering vs jp.pokellector.com set indexes",
    )
    vp.add_argument("--set", dest="sets", action="append", default=None)
    vp.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="HTTP timeout seconds per request (default: 60)",
    )

    ac = sub.add_parser(
        "audit-current",
        help="Phase 1: write a rich per-set markdown gap report (no data changes)",
    )
    ac.add_argument(
        "--set",
        dest="target_set",
        default=None,
        help="Only report on a single set",
    )

    af = sub.add_parser(
        "audit-fetch",
        help="Phase 2: scrape TCGCollector for one set and write data/audit/<SET>.yml",
    )
    af.add_argument("--set", dest="sets", action="append", required=True)
    af.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Per-card detail concurrency (default 2; be polite)",
    )
    af.add_argument(
        "--no-bronze",
        action="store_true",
        help="Skip MinIO bronze mirroring (testing/dev)",
    )

    ad = sub.add_parser(
        "audit-diff",
        help="Phase 3: diff data/audit/*.yml vs data/cards/** and emit reports",
    )
    ad.add_argument("--set", dest="target_set", default=None)

    afb = sub.add_parser(
        "audit-fallback",
        help="Phase 4: fallback oracle (pokemon-card.com / Bulbapedia) for conflicts",
    )
    afb.add_argument("--set", dest="sets", action="append", required=True)
    afb.add_argument(
        "--field",
        choices=("name_ja", "name_en", "illustrator"),
        required=True,
    )

    aap = sub.add_parser(
        "audit-apply",
        help="Phase 5: apply audit values to data/cards/<SET>/<NNN>.yml",
    )
    aap.add_argument("--tsv", required=True, help="Diff TSV emitted by audit-diff")
    grp = aap.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--auto",
        action="store_true",
        help="Apply only AUTO_FILL rows (current=null, oracle non-null)",
    )
    grp.add_argument(
        "--review",
        action="store_true",
        help=(
            "Apply rows the operator hand-edited (column `chosen` non-empty); "
            "prepends `# manual: true` to each modified file."
        ),
    )
    aap.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing",
    )

    return p


async def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "seed-sets":
        from watari_catalog import seed_sets

        await seed_sets.run()
        return 0
    if args.command == "bootstrap-set":
        from watari_catalog import bootstrap

        await bootstrap.run(args.sets, no_fetch=args.no_fetch)
        return 0
    if args.command == "seed-cards":
        from watari_catalog import seed_cards

        await seed_cards.run(args.sets)
        return 0
    if args.command == "verify":
        from watari_catalog import verify

        return await verify.run(strict=args.strict)
    if args.command == "verify-pokellector":
        from watari_catalog import verify_pokellector

        return await verify_pokellector.run(
            sets=args.sets,
            timeout=args.timeout,
        )
    if args.command == "audit-current":
        from watari_catalog import audit_current

        await audit_current.run(target_set=args.target_set)
        return 0
    if args.command == "audit-fetch":
        from watari_catalog import audit_fetch

        return await audit_fetch.run(
            sets=args.sets,
            concurrency=args.concurrency,
            bronze=not args.no_bronze,
        )
    if args.command == "audit-diff":
        from watari_catalog import audit_diff

        return await audit_diff.run(target_set=args.target_set)
    if args.command == "audit-fallback":
        from watari_catalog import audit_fallback

        return await audit_fallback.run(sets=args.sets, field=args.field)
    if args.command == "audit-apply":
        from watari_catalog import audit_apply

        return await audit_apply.run(
            tsv_path=args.tsv,
            auto=args.auto,
            review=args.review,
            dry_run=args.dry_run,
        )
    return 1


def main() -> None:
    args = _build_parser().parse_args()
    _configure_logging(args.log_level)
    sys.exit(asyncio.run(_dispatch(args)))


if __name__ == "__main__":
    main()
