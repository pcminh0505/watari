"""Phase 5 — apply audit oracle values to ``data/cards/<SET>/<NNN>.yml``.

Two modes:

- ``--auto`` writes only ``AUTO_FILL`` rows from the diff TSV (current
  null, oracle non-null). It does **not** prepend ``# manual: true`` —
  these are recoverable by re-bootstrapping if the oracle changes.
- ``--auto --conflicts`` additionally applies ``CONFLICT`` rows using the
  oracle column (TCGCollector wins). Same no-``manual`` banner as plain
  ``--auto`` — re-bootstrap may revert if source precedence disagrees.
- ``--review`` writes whichever rows have a non-empty ``chosen`` cell
  (the operator hand-fills these for ``CONFLICT`` rows). It **does**
  prepend ``# manual: true`` so the bootstrap pipeline can't overwrite
  the operator's choice.

In both modes:

- Files with ``# manual: true`` on line 1 are skipped (CLAUDE.md §6
  invariant 3 — operator-frozen YMLs are never overwritten by audit).
- ``ruamel.yaml`` is used for round-trip preservation of comments + key
  order; the existing emit_yml banner is preserved verbatim.
- A summary of writes / skips / conflicts is printed and returned.
"""

from __future__ import annotations

import csv
import dataclasses
import logging
import pathlib
from collections import Counter
from typing import Any

from ruamel.yaml import YAML

from watari_catalog.paths import card_yaml_path, cards_set_dir

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


SUPPORTED_FIELDS: frozenset[str] = frozenset(
    {"name_ja", "name_en", "rarity_code", "illustrator"}
)
AUTO_FILL = "AUTO_FILL"
CONFLICT = "CONFLICT"
MANUAL_HEADER = "# manual: true\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _yaml() -> YAML:
    y = YAML()
    y.default_flow_style = False
    y.allow_unicode = True
    y.width = 1000
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _read_tsv(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)


def _load_card_text(set_code: str, local_id: str) -> tuple[pathlib.Path, str] | None:
    """Locate the card YML (try padded + unpadded local_id) and return its text."""
    set_dir = cards_set_dir(set_code)
    candidates = [
        card_yaml_path(set_code, local_id.zfill(3)),
        set_dir / f"{local_id}.yml",
    ]
    for p in candidates:
        if p.exists():
            return p, p.read_text(encoding="utf-8")
    return None


def _is_manual(text: str) -> bool:
    head = text.splitlines()[:3]
    return any(line.strip().lower().startswith("# manual: true") for line in head)


def _split_banner(text: str) -> tuple[str, str]:
    """Split the YML text into (banner_comments, body)."""
    lines = text.splitlines(keepends=True)
    banner: list[str] = []
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("#") or line.strip() == "":
            banner.append(line)
        else:
            body_start = i
            break
    return "".join(banner), "".join(lines[body_start:])


def _ensure_manual_marker(banner: str) -> str:
    """Make sure ``# manual: true`` is on line 1 of the banner."""
    if banner and banner.lstrip().lower().startswith("# manual: true"):
        return banner
    return MANUAL_HEADER + banner.lstrip("\n")


# ---------------------------------------------------------------------------
# Apply core
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ApplyResult:
    written: int = 0
    skipped_manual: int = 0
    skipped_unchanged: int = 0
    skipped_missing_yml: int = 0
    skipped_unsupported: int = 0
    by_set: Counter[str] = dataclasses.field(default_factory=Counter)
    examples: list[tuple[str, str, str, str | None, str | None]] = (
        dataclasses.field(default_factory=list)
    )

    def summary(self) -> dict[str, Any]:
        return {
            "written": self.written,
            "skipped_manual": self.skipped_manual,
            "skipped_unchanged": self.skipped_unchanged,
            "skipped_missing_yml": self.skipped_missing_yml,
            "skipped_unsupported": self.skipped_unsupported,
            "by_set": dict(self.by_set),
        }


def _apply_field(doc: dict[str, Any], field: str, value: str | None) -> bool:
    """Set ``field`` on ``doc`` to ``value``. Returns True if changed."""
    current = doc.get(field)
    if current == value:
        return False
    if value is None or value == "":
        # Don't blank a non-null field via apply — that would be a regression.
        return False
    doc[field] = value
    return True


def _row_is_applicable(
    row: dict[str, str], *, mode: str, include_conflicts: bool
) -> tuple[bool, str | None]:
    """Return ``(applicable, chosen_value)``.

    For ``--auto`` mode: only ``AUTO_FILL`` rows are applicable; the
    chosen value is the oracle column. With ``include_conflicts=True``,
    ``CONFLICT`` rows also apply when oracle is non-empty (oracle wins).
    For ``--review`` mode: any row with a non-empty ``chosen`` cell is
    applicable; the chosen value is the ``chosen`` column.
    """
    cls = (row.get("classification") or "").strip()
    if mode == "auto":
        oracle = (row.get("oracle") or "").strip()
        if cls == AUTO_FILL:
            if not oracle:
                return False, None
            return True, oracle
        if include_conflicts and cls == CONFLICT:
            if not oracle:
                return False, None
            return True, oracle
        return False, None
    if mode == "review":
        chosen = (row.get("chosen") or "").strip()
        if not chosen:
            return False, None
        return True, chosen
    raise ValueError(f"unknown mode {mode!r}")


def _apply_one_row(
    row: dict[str, str],
    *,
    mode: str,
    include_conflicts: bool,
    dry_run: bool,
    result: ApplyResult,
) -> None:
    field = (row.get("field") or "").strip()
    if field not in SUPPORTED_FIELDS:
        result.skipped_unsupported += 1
        return

    applicable, chosen = _row_is_applicable(
        row, mode=mode, include_conflicts=include_conflicts
    )
    if not applicable:
        return

    set_code = (row.get("set_code") or "").upper()
    local_id = (row.get("local_id") or "").strip()
    if not set_code or not local_id:
        return

    loaded = _load_card_text(set_code, local_id)
    if loaded is None:
        result.skipped_missing_yml += 1
        return
    path, text = loaded

    if _is_manual(text):
        result.skipped_manual += 1
        return

    banner, body = _split_banner(text)
    yaml_io = _yaml()
    import io as _io

    doc = yaml_io.load(_io.StringIO(body))
    if doc is None:
        return

    changed = _apply_field(doc, field, chosen)
    if not changed:
        result.skipped_unchanged += 1
        return

    if mode == "review":
        new_banner = _ensure_manual_marker(banner)
    else:
        new_banner = banner

    buf = _io.StringIO()
    yaml_io.dump(doc, buf)
    new_text = new_banner + buf.getvalue()
    if not new_text.endswith("\n"):
        new_text += "\n"

    if dry_run:
        result.examples.append((set_code, local_id, field, row.get("current"), chosen))
        result.written += 1
        result.by_set[set_code] += 1
        return

    path.write_text(new_text, encoding="utf-8")
    result.written += 1
    result.by_set[set_code] += 1
    result.examples.append((set_code, local_id, field, row.get("current"), chosen))


# ---------------------------------------------------------------------------
# Public CLI entrypoint
# ---------------------------------------------------------------------------


async def run(
    *,
    tsv_path: str,
    auto: bool,
    review: bool,
    include_conflicts: bool = False,
    dry_run: bool,
) -> int:
    if auto == review:
        # argparse mutex prevents both, but be defensive.
        logger.error("audit-apply: pass exactly one of --auto / --review")
        return 2
    if include_conflicts and not auto:
        logger.error("audit-apply: --conflicts is only valid with --auto")
        return 2
    mode = "auto" if auto else "review"

    p = pathlib.Path(tsv_path)
    if not p.exists():
        logger.error("audit-apply: TSV not found: %s", p)
        return 1
    rows = _read_tsv(p)

    result = ApplyResult()
    for row in rows:
        _apply_one_row(
            row,
            mode=mode,
            include_conflicts=include_conflicts,
            dry_run=dry_run,
            result=result,
        )

    mode_label = mode
    if mode == "auto" and include_conflicts:
        mode_label = "auto+conflicts"
    print(
        f"audit-apply ({mode_label}{', dry-run' if dry_run else ''}): "
        f"written={result.written} "
        f"skipped_manual={result.skipped_manual} "
        f"skipped_unchanged={result.skipped_unchanged} "
        f"skipped_missing_yml={result.skipped_missing_yml} "
        f"skipped_unsupported={result.skipped_unsupported}"
    )
    if result.by_set:
        print("  by set:")
        for k, v in sorted(result.by_set.items()):
            print(f"    {k}: {v}")
    if result.examples:
        sample = result.examples[: 10 if dry_run else 5]
        print("  examples:")
        for set_code, lid, field, current, chosen in sample:
            print(
                f"    {set_code}/{lid} {field}: "
                f"{current!r} -> {chosen!r}"
            )
    return 0
