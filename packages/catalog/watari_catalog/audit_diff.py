"""Phase 3 — diff oracle (TCGCollector audit) vs. current (data/cards) YML truth.

For each ``(set_code, local_id, field)`` tuple this module emits one of:

- ``AUTO_FILL`` — current value is null, oracle has a confident value.
- ``MATCH`` — values agree (after canonicalization for rarity).
- ``CONFLICT`` — values disagree; needs operator adjudication.
- ``NO_ORACLE`` — oracle has no value (TCGCollector returned ``"—"``).
- ``NO_CURRENT`` — card YML doesn't exist (oracle has more cards than us).

Outputs:

- ``reports/audit-diff-<set>-<utc>.md`` — human-readable summary.
- ``reports/audit-diff-<set>-<utc>.tsv`` — machine-readable input for the
  ``audit-apply`` command. Columns:
  ``set_code, local_id, field, current, oracle, classification, source_url, chosen``.

The ``chosen`` column is left blank by default; for ``CONFLICT`` rows the
operator hand-edits the TSV, fills in the value they want, and runs
``audit-apply --review`` to write it back into the card YML.

The fields covered are exactly those scoped by the audit (per the user's
question 2 in the plan): ``name_ja``, ``name_en``, ``rarity_code``,
``illustrator``. ``name_ja`` will always be ``NO_ORACLE`` for TCGCollector
because TCGCollector doesn't publish original JP names; Phase 4 hands
those off to ``pokemon-card.com`` / Bulbapedia.
"""

from __future__ import annotations

import csv
import dataclasses
import logging
import pathlib
from collections import Counter
from datetime import UTC, datetime

import yaml

from watari_catalog.paths import (
    audit_dir,
    audit_yaml_path,
    cards_set_dir,
    reports_dir,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


TRACKED_FIELDS: tuple[str, ...] = (
    "name_ja",
    "name_en",
    "rarity_code",
    "illustrator",
)


# Classifications
AUTO_FILL = "AUTO_FILL"
MATCH = "MATCH"
CONFLICT = "CONFLICT"
NO_ORACLE = "NO_ORACLE"
NO_CURRENT = "NO_CURRENT"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CurrentCard:
    set_code: str
    local_id: str
    name_ja: str | None
    name_en: str | None
    rarity_code: str | None
    illustrator: str | None
    is_manual: bool


@dataclasses.dataclass
class OracleCard:
    set_code: str
    local_id: str
    name_en: str | None
    rarity_canon: str | None
    illustrator: str | None
    detail_url: str | None


def _is_manual(text: str) -> bool:
    head = text.splitlines()[:3]
    return any(line.strip().lower().startswith("# manual: true") for line in head)


def _load_current(set_code: str) -> dict[str, CurrentCard]:
    set_dir = cards_set_dir(set_code)
    out: dict[str, CurrentCard] = {}
    if not set_dir.is_dir():
        return out
    for path in sorted(set_dir.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        raw = yaml.safe_load(text) or {}
        if not isinstance(raw, dict):
            continue
        local_id = str(raw.get("local_id") or path.stem)
        out[local_id] = CurrentCard(
            set_code=str(raw.get("set_code") or set_code).upper(),
            local_id=local_id,
            name_ja=raw.get("name_ja"),
            name_en=raw.get("name_en"),
            rarity_code=raw.get("rarity_code"),
            illustrator=raw.get("illustrator"),
            is_manual=_is_manual(text),
        )
    return out


def _load_oracle(set_code: str) -> dict[str, OracleCard]:
    path = audit_yaml_path(set_code)
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, OracleCard] = {}
    for c in raw.get("cards") or []:
        local_id = str(c.get("local_id") or "").zfill(3) if c.get("local_id") else None
        if not local_id:
            continue
        out[local_id] = OracleCard(
            set_code=str(raw.get("set_code") or set_code).upper(),
            local_id=local_id,
            name_en=c.get("name_en"),
            rarity_canon=c.get("rarity_canon"),
            illustrator=c.get("illustrator"),
            detail_url=c.get("detail_url"),
        )
    return out


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _norm_text(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


def _eq_canon_rarity(current: str | None, oracle_canon: str | None) -> bool:
    if current is None or oracle_canon is None:
        return False
    return current.strip().upper() == oracle_canon.strip().upper()


def _eq_text(current: str | None, oracle: str | None) -> bool:
    a = _norm_text(current).casefold()
    b = _norm_text(oracle).casefold()
    if not a or not b:
        return False
    return a == b


def classify_field(
    field: str,
    current_value: str | None,
    oracle_value: str | None,
) -> str:
    """Return one of AUTO_FILL / MATCH / CONFLICT / NO_ORACLE."""
    if oracle_value is None or _norm_text(oracle_value) == "":
        return NO_ORACLE
    if current_value is None or _norm_text(current_value) == "":
        return AUTO_FILL
    if field == "rarity_code":
        return MATCH if _eq_canon_rarity(current_value, oracle_value) else CONFLICT
    return MATCH if _eq_text(current_value, oracle_value) else CONFLICT


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class DiffRow:
    set_code: str
    local_id: str
    field: str
    current: str | None
    oracle: str | None
    classification: str
    source_url: str | None
    is_manual: bool


def _diff_one_set(
    set_code: str,
    current: dict[str, CurrentCard],
    oracle: dict[str, OracleCard],
) -> list[DiffRow]:
    rows: list[DiffRow] = []
    all_ids = sorted(current.keys() | oracle.keys())

    for lid in all_ids:
        cur = current.get(lid)
        ora = oracle.get(lid)
        if cur is None and ora is not None:
            # Oracle has a card we don't (e.g. promo, late addition).
            for field in TRACKED_FIELDS:
                rows.append(
                    DiffRow(
                        set_code=set_code,
                        local_id=lid,
                        field=field,
                        current=None,
                        oracle=_oracle_value_for_field(ora, field),
                        classification=NO_CURRENT,
                        source_url=ora.detail_url,
                        is_manual=False,
                    )
                )
            continue

        if cur is None:
            continue

        for field in TRACKED_FIELDS:
            current_val = _current_value_for_field(cur, field)
            oracle_val = _oracle_value_for_field(ora, field) if ora else None
            cls = classify_field(field, current_val, oracle_val)
            rows.append(
                DiffRow(
                    set_code=set_code,
                    local_id=lid,
                    field=field,
                    current=current_val,
                    oracle=oracle_val,
                    classification=cls,
                    source_url=ora.detail_url if ora else None,
                    is_manual=cur.is_manual,
                )
            )

    return rows


def _current_value_for_field(c: CurrentCard, field: str) -> str | None:
    return getattr(c, field, None)


def _oracle_value_for_field(o: OracleCard | None, field: str) -> str | None:
    if o is None:
        return None
    if field == "name_ja":
        # TCGCollector intentionally has no JA names — defer to Phase 4.
        return None
    if field == "name_en":
        return o.name_en
    if field == "rarity_code":
        return o.rarity_canon
    if field == "illustrator":
        return o.illustrator
    return None


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def _render_markdown(
    rows: list[DiffRow],
    *,
    sets_covered: list[str],
    generated_at: datetime,
) -> str:
    out: list[str] = []
    out.append(f"# Audit diff (TCGCollector vs current YMLs) — {generated_at.isoformat()}")
    out.append("")
    out.append(
        f"Sets covered: **{len(sets_covered)}** "
        f"({', '.join(sets_covered) if len(sets_covered) <= 10 else f'{len(sets_covered)} sets'})"
    )
    out.append("")

    by_class = Counter(r.classification for r in rows)
    out.append("## Classification totals")
    out.append("")
    for cls in (AUTO_FILL, CONFLICT, MATCH, NO_ORACLE, NO_CURRENT):
        out.append(f"- {cls}: {by_class.get(cls, 0)}")
    out.append("")

    by_field = Counter((r.field, r.classification) for r in rows)
    out.append("## By field")
    out.append("")
    out.append("| field | AUTO_FILL | MATCH | CONFLICT | NO_ORACLE |")
    out.append("|-------|-----------|-------|----------|-----------|")
    for f in TRACKED_FIELDS:
        out.append(
            f"| {f} | {by_field.get((f, AUTO_FILL), 0)} | "
            f"{by_field.get((f, MATCH), 0)} | {by_field.get((f, CONFLICT), 0)} | "
            f"{by_field.get((f, NO_ORACLE), 0)} |"
        )
    out.append("")

    # AUTO_FILL preview — operators usually want to see this immediately.
    af = [r for r in rows if r.classification == AUTO_FILL]
    if af:
        out.append("## AUTO_FILL preview (first 30)")
        out.append("")
        out.append("| set | local_id | field | oracle |")
        out.append("|-----|---------:|-------|--------|")
        for r in af[:30]:
            out.append(
                f"| {r.set_code} | {r.local_id} | {r.field} | {r.oracle or ''} |"
            )
        if len(af) > 30:
            out.append(f"\n_…and {len(af) - 30} more._")
        out.append("")

    # CONFLICT preview — full list, since operator must address each one.
    conflicts = [r for r in rows if r.classification == CONFLICT]
    if conflicts:
        out.append("## CONFLICT (operator must adjudicate)")
        out.append("")
        out.append("| set | local_id | field | current | oracle | manual? |")
        out.append("|-----|---------:|-------|---------|--------|--------:|")
        for r in conflicts:
            out.append(
                f"| {r.set_code} | {r.local_id} | {r.field} | "
                f"`{(r.current or '').replace('|', '\\|')}` | "
                f"`{(r.oracle or '').replace('|', '\\|')}` | "
                f"{'yes' if r.is_manual else ''} |"
            )
        out.append("")

    out.append("---")
    out.append("")
    out.append(
        "Apply the AUTO_FILL rows with: "
        "`uv run python -m watari_catalog audit-apply --tsv reports/audit-diff-...tsv --auto`. "
        "For CONFLICT rows: edit the TSV (fill the `chosen` column), then run "
        "`audit-apply --tsv ... --review` to commit the operator-chosen values "
        "and freeze them with `# manual: true`."
    )
    return "\n".join(out)


def _write_tsv(rows: list[DiffRow], path: pathlib.Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "set_code",
                "local_id",
                "field",
                "current",
                "oracle",
                "classification",
                "source_url",
                "is_manual",
                "chosen",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.set_code,
                    r.local_id,
                    r.field,
                    r.current if r.current is not None else "",
                    r.oracle if r.oracle is not None else "",
                    r.classification,
                    r.source_url or "",
                    "yes" if r.is_manual else "",
                    "",  # `chosen` — operator fills in for CONFLICT rows
                ]
            )


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


async def run(*, target_set: str | None = None) -> int:
    audit_root = audit_dir()
    if not audit_root.is_dir():
        logger.error("audit-diff: %s does not exist", audit_root)
        return 1

    if target_set:
        candidates = [target_set.upper()]
    else:
        candidates = [
            p.stem.upper()
            for p in sorted(audit_root.glob("*.yml"))
            if p.is_file() and p.name != ".gitkeep"
        ]
    if not candidates:
        logger.warning(
            "audit-diff: no audit files in %s — run `audit-fetch` first",
            audit_root,
        )
        return 1

    rows: list[DiffRow] = []
    sets_covered: list[str] = []
    for set_code in candidates:
        oracle = _load_oracle(set_code)
        if not oracle:
            logger.warning("audit-diff %s: no oracle data, skipping", set_code)
            continue
        current = _load_current(set_code)
        if not current:
            logger.warning(
                "audit-diff %s: no card YMLs under data/cards/%s, skipping",
                set_code,
                set_code,
            )
            continue
        set_rows = _diff_one_set(set_code, current, oracle)
        rows.extend(set_rows)
        sets_covered.append(set_code)

    if not rows:
        logger.warning("audit-diff: nothing to diff")
        return 1

    generated_at = datetime.now(UTC).replace(microsecond=0)
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    reports_dir().mkdir(parents=True, exist_ok=True)
    target = target_set.upper() if target_set else "all"
    md_path = reports_dir() / f"audit-diff-{target}-{stamp}.md"
    tsv_path = reports_dir() / f"audit-diff-{target}-{stamp}.tsv"

    md_path.write_text(
        _render_markdown(rows, sets_covered=sets_covered, generated_at=generated_at),
        encoding="utf-8",
    )
    _write_tsv(rows, tsv_path)

    by_class = Counter(r.classification for r in rows)
    print(
        "audit-diff: "
        f"sets={len(sets_covered)} rows={len(rows)} "
        f"AUTO_FILL={by_class.get(AUTO_FILL, 0)} "
        f"MATCH={by_class.get(MATCH, 0)} "
        f"CONFLICT={by_class.get(CONFLICT, 0)} "
        f"NO_ORACLE={by_class.get(NO_ORACLE, 0)} "
        f"NO_CURRENT={by_class.get(NO_CURRENT, 0)}"
    )
    print(f"  md  → {md_path}")
    print(f"  tsv → {tsv_path}")

    return 0
