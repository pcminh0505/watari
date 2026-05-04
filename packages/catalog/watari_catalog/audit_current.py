"""Phase 1 audit reporter: rich health snapshot of the *current* catalog.

This is a strict superset of ``verify.py``. Where ``verify`` prints a single
table to stdout, ``audit-current`` walks ``data/cards/**/*.yml`` (the source
of truth — bootstrap is destructive, so the YMLs are richer than the DB
between runs) and produces:

    * a per-set breakdown of nulls (name_ja, name_en, rarity_code, illustrator)
    * a per-rarity breakdown of name_ja nulls inside each set so we can see
      whether the gap is "all commons" or "V/VMAX/GX full-arts"
    * a global list of source disagreements: cards where the Pokellector
      ``rarity_raw`` and the canonicalized TCGdex rarity disagree, the
      Pokellector category looks wrong vs. our category heuristic, etc.

Output is written to ``reports/catalog-audit-<UTC>.md``. No data is mutated.

Run: ``uv run python -m watari_catalog audit-current [--set SV2A]``
"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

import yaml

from watari_catalog.paths import cards_dir, cards_set_dir, reports_dir
from watari_catalog.rarities import canonicalize_pokellector, canonicalize_tcgdex

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CardSnapshot:
    set_code: str
    local_id: str
    name_ja: str | None
    name_en: str | None
    rarity_code: str | None
    illustrator: str | None
    category: str | None
    image_url: str | None
    pokellector_rarity_raw: str | None
    tcgdex_rarity_raw: str | None
    cardrush_rarity_code: str | None
    is_manual: bool


@dataclasses.dataclass
class SetReport:
    set_code: str
    total_cards: int
    null_name_ja: list[str] = dataclasses.field(default_factory=list)
    null_name_en: list[str] = dataclasses.field(default_factory=list)
    null_rarity: list[str] = dataclasses.field(default_factory=list)
    null_illustrator: list[str] = dataclasses.field(default_factory=list)
    null_image: list[str] = dataclasses.field(default_factory=list)
    null_name_ja_by_rarity: Counter[str] = dataclasses.field(default_factory=Counter)
    rarity_disagreements: list[tuple[str, str | None, str | None, str | None]] = (
        dataclasses.field(default_factory=list)
    )

    @property
    def health_score(self) -> float:
        """0..1 — fraction of (4 fields × N cards) that are non-null."""
        if self.total_cards == 0:
            return 1.0
        slots = self.total_cards * 4
        nulls = (
            len(self.null_name_ja)
            + len(self.null_name_en)
            + len(self.null_rarity)
            + len(self.null_illustrator)
        )
        return max(0.0, min(1.0, 1.0 - nulls / slots))


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _is_manual(text: str) -> bool:
    head = text.splitlines()[:3]
    return any(line.strip().lower().startswith("# manual: true") for line in head)


def _load_card_snapshot(path: pathlib.Path) -> CardSnapshot | None:
    text = path.read_text(encoding="utf-8")
    raw: dict[str, Any] | None = yaml.safe_load(text)
    if not isinstance(raw, dict):
        return None
    sources = raw.get("sources") or {}
    poke_src = sources.get("pokellector") or {}
    tcg_src = sources.get("tcgdex") or {}
    cr_src = sources.get("cardrush") or {}
    return CardSnapshot(
        set_code=str(raw.get("set_code") or path.parent.name).upper(),
        local_id=str(raw.get("local_id") or path.stem),
        name_ja=raw.get("name_ja"),
        name_en=raw.get("name_en"),
        rarity_code=raw.get("rarity_code"),
        illustrator=raw.get("illustrator"),
        category=raw.get("category"),
        image_url=raw.get("image"),
        pokellector_rarity_raw=poke_src.get("rarity_raw"),
        tcgdex_rarity_raw=tcg_src.get("rarity_raw"),
        cardrush_rarity_code=cr_src.get("rarity_code"),
        is_manual=_is_manual(text),
    )


def _iter_set_codes(target_set: str | None) -> list[str]:
    if not cards_dir().exists():
        return []
    if target_set:
        d = cards_set_dir(target_set)
        return [d.name] if d.is_dir() else []
    return sorted(d.name for d in cards_dir().iterdir() if d.is_dir())


def _scan_set(set_code: str) -> list[CardSnapshot]:
    set_dir = cards_set_dir(set_code)
    out: list[CardSnapshot] = []
    if not set_dir.is_dir():
        return out
    for p in sorted(set_dir.glob("*.yml")):
        try:
            snap = _load_card_snapshot(p)
        except Exception as exc:
            logger.warning("audit_current: failed to load %s: %s", p, exc)
            continue
        if snap is not None:
            out.append(snap)
    return out


# ---------------------------------------------------------------------------
# Reduction
# ---------------------------------------------------------------------------


def _build_set_report(set_code: str, cards: list[CardSnapshot]) -> SetReport:
    rep = SetReport(set_code=set_code, total_cards=len(cards))

    for c in cards:
        if c.name_ja is None or c.name_ja == "":
            rep.null_name_ja.append(c.local_id)
            rarity_bucket = c.rarity_code or "?"
            rep.null_name_ja_by_rarity[rarity_bucket] += 1
        if c.name_en is None or c.name_en == "":
            rep.null_name_en.append(c.local_id)
        if c.rarity_code is None or c.rarity_code == "":
            rep.null_rarity.append(c.local_id)
        if c.illustrator is None or c.illustrator == "":
            rep.null_illustrator.append(c.local_id)
        if c.image_url is None or c.image_url == "":
            rep.null_image.append(c.local_id)

        # Cross-source rarity disagreement detection.
        poke_canon = canonicalize_pokellector(c.pokellector_rarity_raw)
        tcg_canon = canonicalize_tcgdex(c.tcgdex_rarity_raw)
        if poke_canon and tcg_canon and poke_canon != tcg_canon:
            rep.rarity_disagreements.append(
                (c.local_id, poke_canon, tcg_canon, c.rarity_code)
            )

    return rep


# ---------------------------------------------------------------------------
# Markdown writer
# ---------------------------------------------------------------------------


def _format_id_list(ids: list[str], *, limit: int = 20) -> str:
    head = ", ".join(ids[:limit])
    tail = f", … (+{len(ids) - limit} more)" if len(ids) > limit else ""
    return head + tail


def render_markdown(reports: list[SetReport], generated_at: datetime) -> str:
    out: list[str] = []
    out.append(f"# Catalog data-quality snapshot — {generated_at.isoformat()}")
    out.append("")
    out.append(
        "Walks `data/cards/**/*.yml` (source of truth) and reports current "
        "field-level gaps. **No data was modified.** This is the Phase 1 "
        "input to the TCGCollector-anchored audit; downstream phases (2-7) "
        "fix the gaps surfaced here."
    )
    out.append("")

    # ---- totals -------------------------------------------------------------
    total_cards = sum(r.total_cards for r in reports)
    total_null_ja = sum(len(r.null_name_ja) for r in reports)
    total_null_en = sum(len(r.null_name_en) for r in reports)
    total_null_rar = sum(len(r.null_rarity) for r in reports)
    total_null_ill = sum(len(r.null_illustrator) for r in reports)
    total_null_img = sum(len(r.null_image) for r in reports)
    total_disagreements = sum(len(r.rarity_disagreements) for r in reports)

    out.append("## Totals")
    out.append("")
    out.append(f"- Sets scanned: **{len(reports)}**")
    out.append(f"- Cards (artwork rows): **{total_cards}**")
    out.append(f"- Missing `name_ja`: **{total_null_ja}**")
    out.append(f"- Missing `name_en`: **{total_null_en}**")
    out.append(f"- Missing `rarity_code`: **{total_null_rar}**")
    out.append(f"- Missing `illustrator`: **{total_null_ill}**")
    out.append(f"- Missing `image` (sanity): **{total_null_img}**")
    out.append(
        f"- Pokellector ↔ TCGdex rarity disagreements: **{total_disagreements}**"
    )
    out.append("")

    # ---- worst sets ---------------------------------------------------------
    worst = sorted(
        reports,
        key=lambda r: (
            len(r.null_name_ja),
            len(r.null_rarity),
            len(r.null_illustrator),
        ),
        reverse=True,
    )[:15]

    out.append("## Top 15 sets by `name_ja` gap")
    out.append("")
    out.append("| set | total | null_ja | null_en | null_rar | null_ill | health |")
    out.append("|-----|------:|--------:|--------:|---------:|---------:|-------:|")
    for r in worst:
        out.append(
            f"| {r.set_code} | {r.total_cards} | {len(r.null_name_ja)} | "
            f"{len(r.null_name_en)} | {len(r.null_rarity)} | "
            f"{len(r.null_illustrator)} | {r.health_score:.2f} |"
        )
    out.append("")

    # ---- per-set details ----------------------------------------------------
    out.append("## Per-set detail")
    out.append("")
    for r in sorted(reports, key=lambda r: r.set_code):
        if r.total_cards == 0:
            continue
        gaps = (
            len(r.null_name_ja)
            + len(r.null_name_en)
            + len(r.null_rarity)
            + len(r.null_illustrator)
        )
        # Skip clean sets to keep the report short
        if gaps == 0 and not r.rarity_disagreements:
            continue

        out.append(f"### {r.set_code}  (n={r.total_cards}, health={r.health_score:.2f})")
        out.append("")

        if r.null_name_ja:
            out.append(
                f"- **null `name_ja` ({len(r.null_name_ja)})**: "
                f"{_format_id_list(r.null_name_ja)}"
            )
            if r.null_name_ja_by_rarity:
                buckets = ", ".join(
                    f"{k}={v}" for k, v in sorted(r.null_name_ja_by_rarity.items())
                )
                out.append(f"  - by rarity: {buckets}")
        if r.null_name_en:
            out.append(
                f"- **null `name_en` ({len(r.null_name_en)})**: "
                f"{_format_id_list(r.null_name_en)}"
            )
        if r.null_rarity:
            out.append(
                f"- **null `rarity_code` ({len(r.null_rarity)})**: "
                f"{_format_id_list(r.null_rarity)}"
            )
        if r.null_illustrator:
            out.append(
                f"- **null `illustrator` ({len(r.null_illustrator)})**: "
                f"{_format_id_list(r.null_illustrator)}"
            )
        if r.rarity_disagreements:
            out.append(
                f"- **Pokellector ≠ TCGdex on rarity "
                f"({len(r.rarity_disagreements)})**:"
            )
            for lid, p, t, current in r.rarity_disagreements[:8]:
                out.append(
                    f"  - `{lid}`: pokellector={p} · tcgdex={t} · current={current}"
                )
            if len(r.rarity_disagreements) > 8:
                out.append(
                    f"  - … (+{len(r.rarity_disagreements) - 8} more)"
                )
        out.append("")

    out.append("---")
    out.append("")
    out.append(
        "Generated by `python -m watari_catalog audit-current`. Re-run after "
        "applying any audit fixes to confirm the gap shrinks."
    )
    out.append("")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


async def run(*, target_set: str | None = None) -> dict[str, Any]:
    """Build the Phase-1 health snapshot and write it to ``reports/``."""
    reports: list[SetReport] = []
    set_codes = _iter_set_codes(target_set)
    if not set_codes:
        logger.warning("audit-current: no sets found under %s", cards_dir())
        return {"sets": [], "report_path": None}

    rarity_disagreement_global: list[tuple[str, str, str | None, str | None]] = []
    by_rarity_global: Counter[str] = Counter()

    for set_code in set_codes:
        cards = _scan_set(set_code)
        rep = _build_set_report(set_code, cards)
        reports.append(rep)
        for lid, p, t, _cur in rep.rarity_disagreements:
            rarity_disagreement_global.append((rep.set_code, lid, p, t))
        by_rarity_global.update(rep.null_name_ja_by_rarity)

    generated_at = datetime.now(UTC).replace(microsecond=0)
    report_md = render_markdown(reports, generated_at)

    reports_dir().mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    target = target_set.upper() if target_set else "all"
    report_path = reports_dir() / f"catalog-audit-{target}-{stamp}.md"
    report_path.write_text(report_md, encoding="utf-8")

    logger.info(
        "audit-current: %d sets scanned, %d total cards, report → %s",
        len(reports),
        sum(r.total_cards for r in reports),
        report_path,
    )

    # Compact stdout summary so CLI users see the headlines.
    total_null_ja = sum(len(r.null_name_ja) for r in reports)
    total_null_rar = sum(len(r.null_rarity) for r in reports)
    total_null_ill = sum(len(r.null_illustrator) for r in reports)
    print(
        "audit-current: "
        f"sets={len(reports)} "
        f"cards={sum(r.total_cards for r in reports)} "
        f"null_ja={total_null_ja} "
        f"null_rar={total_null_rar} "
        f"null_ill={total_null_ill} "
        f"disagreements={len(rarity_disagreement_global)}"
    )
    print(f"audit-current: report written to {report_path}")

    return {
        "sets": [
            {
                "set_code": r.set_code,
                "total_cards": r.total_cards,
                "null_name_ja": len(r.null_name_ja),
                "null_name_en": len(r.null_name_en),
                "null_rarity": len(r.null_rarity),
                "null_illustrator": len(r.null_illustrator),
                "rarity_disagreements": len(r.rarity_disagreements),
                "health": r.health_score,
            }
            for r in reports
        ],
        "report_path": str(report_path),
    }
