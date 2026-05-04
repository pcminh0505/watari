"""Unit tests for the Phase-3 ``audit-diff`` classifier.

Exercises ``classify_field`` plus the per-set diff stitching so we lock
in the contract:

- ``name_ja`` always classifies as ``NO_ORACLE`` against TCGCollector
  (the oracle never publishes JP names).
- Rarity equality is canonicalized (case-insensitive whitespace-trimmed).
- Other fields use case-folded text equality.
- Empty/whitespace strings on either side are treated as "missing".
"""

from __future__ import annotations

import pytest
from watari_catalog.audit_diff import (
    AUTO_FILL,
    CONFLICT,
    MATCH,
    NO_CURRENT,
    NO_ORACLE,
    TRACKED_FIELDS,
    CurrentCard,
    DiffRow,
    OracleCard,
    _diff_one_set,
    classify_field,
)


def _current(
    *,
    set_code: str = "SV4A",
    local_id: str = "001",
    name_ja: str | None = None,
    name_en: str | None = None,
    rarity_code: str | None = None,
    illustrator: str | None = None,
    is_manual: bool = False,
) -> CurrentCard:
    return CurrentCard(
        set_code=set_code,
        local_id=local_id,
        name_ja=name_ja,
        name_en=name_en,
        rarity_code=rarity_code,
        illustrator=illustrator,
        is_manual=is_manual,
    )


def _oracle(
    *,
    set_code: str = "SV4A",
    local_id: str = "001",
    name_en: str | None = None,
    rarity_canon: str | None = None,
    illustrator: str | None = None,
    detail_url: str | None = "https://www.tcgcollector.com/cards/1/foo",
) -> OracleCard:
    return OracleCard(
        set_code=set_code,
        local_id=local_id,
        name_en=name_en,
        rarity_canon=rarity_canon,
        illustrator=illustrator,
        detail_url=detail_url,
    )


class TestClassifyField:
    def test_oracle_missing_is_no_oracle(self) -> None:
        assert classify_field("name_en", "Pikachu", None) == NO_ORACLE
        assert classify_field("name_en", "Pikachu", "") == NO_ORACLE
        assert classify_field("name_en", "Pikachu", "   ") == NO_ORACLE

    def test_current_missing_is_auto_fill(self) -> None:
        assert classify_field("name_en", None, "Pikachu") == AUTO_FILL
        assert classify_field("illustrator", "", "Yuu Nishida") == AUTO_FILL
        assert classify_field("rarity_code", "  ", "SAR") == AUTO_FILL

    def test_text_match(self) -> None:
        assert classify_field("name_en", "Pikachu", "Pikachu") == MATCH

    def test_text_match_is_case_insensitive(self) -> None:
        assert classify_field("name_en", "PIKACHU", "pikachu") == MATCH

    def test_text_match_strips_whitespace(self) -> None:
        assert classify_field("illustrator", "  kawayoo  ", "kawayoo") == MATCH

    def test_text_conflict(self) -> None:
        assert classify_field("illustrator", "kawayoo", "Yuu Nishida") == CONFLICT

    def test_rarity_match_uppercases(self) -> None:
        assert classify_field("rarity_code", "sar", "SAR") == MATCH
        assert classify_field("rarity_code", "SAR", "sar") == MATCH

    def test_rarity_conflict(self) -> None:
        # Pokellector says SAR but TCGCollector audit says SSR
        # — exactly the SV4A 320-336 case.
        assert classify_field("rarity_code", "SAR", "SSR") == CONFLICT


class TestDiffOneSet:
    def test_emits_one_row_per_field_per_card(self) -> None:
        current = {
            "001": _current(local_id="001", name_en="Bulbasaur", rarity_code="C"),
        }
        oracle = {
            "001": _oracle(local_id="001", name_en="Bulbasaur", rarity_canon="C"),
        }
        rows = _diff_one_set("SV4A", current, oracle)
        # name_ja, name_en, rarity_code, illustrator
        assert len(rows) == len(TRACKED_FIELDS)
        fields = {r.field for r in rows}
        assert fields == set(TRACKED_FIELDS)

    def test_name_ja_is_always_no_oracle_against_tcgcollector(self) -> None:
        current = {"001": _current(local_id="001", name_ja=None)}
        oracle = {"001": _oracle(local_id="001")}
        rows = _diff_one_set("SV4A", current, oracle)
        ja_rows = [r for r in rows if r.field == "name_ja"]
        assert len(ja_rows) == 1
        assert ja_rows[0].classification == NO_ORACLE
        assert ja_rows[0].oracle is None

    def test_oracle_only_card_emits_no_current(self) -> None:
        current: dict[str, CurrentCard] = {}
        oracle = {
            "999": _oracle(
                local_id="999",
                name_en="Promo Pikachu",
                rarity_canon="PR",
                illustrator="Mitsuhiro Arita",
            )
        }
        rows = _diff_one_set("SV4A", current, oracle)
        assert all(r.classification == NO_CURRENT for r in rows)
        assert {r.field for r in rows} == set(TRACKED_FIELDS)

    def test_current_only_card_emits_no_oracle_for_each_field(self) -> None:
        current = {
            "001": _current(
                local_id="001",
                name_ja="ピカチュウ",
                name_en="Pikachu",
                rarity_code="C",
                illustrator="kawayoo",
            )
        }
        oracle: dict[str, OracleCard] = {}
        rows = _diff_one_set("SV4A", current, oracle)
        assert {r.classification for r in rows} == {NO_ORACLE}

    def test_auto_fill_picks_up_missing_illustrator(self) -> None:
        current = {
            "010": _current(
                local_id="010",
                name_ja="フシギダネ",
                name_en="Bulbasaur",
                rarity_code="C",
                illustrator=None,  # ME-era / SM gap we want filled
            ),
        }
        oracle = {
            "010": _oracle(
                local_id="010",
                name_en="Bulbasaur",
                rarity_canon="C",
                illustrator="Yuu Nishida",
            ),
        }
        rows = _diff_one_set("SV4A", current, oracle)
        by_field = {r.field: r for r in rows}
        assert by_field["illustrator"].classification == AUTO_FILL
        assert by_field["illustrator"].oracle == "Yuu Nishida"
        # Nothing else should be auto-fill.
        assert by_field["name_en"].classification == MATCH
        assert by_field["rarity_code"].classification == MATCH
        assert by_field["name_ja"].classification == NO_ORACLE

    def test_propagates_is_manual_flag(self) -> None:
        current = {
            "001": _current(local_id="001", is_manual=True),
        }
        oracle = {"001": _oracle(local_id="001", name_en="X", rarity_canon="C")}
        rows = _diff_one_set("SV4A", current, oracle)
        assert all(r.is_manual for r in rows if r.local_id == "001")

    def test_rarity_conflict_surfaces_with_source_url(self) -> None:
        current = {"001": _current(local_id="001", rarity_code="SAR")}
        oracle = {
            "001": _oracle(
                local_id="001",
                rarity_canon="SSR",
                detail_url="https://www.tcgcollector.com/cards/100/foo",
            )
        }
        rows = _diff_one_set("SV4A", current, oracle)
        rarity_row = next(r for r in rows if r.field == "rarity_code")
        assert rarity_row.classification == CONFLICT
        assert rarity_row.current == "SAR"
        assert rarity_row.oracle == "SSR"
        assert rarity_row.source_url == "https://www.tcgcollector.com/cards/100/foo"


@pytest.mark.parametrize(
    "field, current_val, oracle_val, expected",
    [
        # name_en text match w/ casefold
        ("name_en", "Pikachu", "pikachu", MATCH),
        # rarity normalizes case + whitespace
        ("rarity_code", " sar ", "SAR", MATCH),
        # rarity differs
        ("rarity_code", "SAR", "SSR", CONFLICT),
        # current missing
        ("illustrator", None, "kawayoo", AUTO_FILL),
        # oracle missing
        ("illustrator", "kawayoo", None, NO_ORACLE),
        # both missing
        ("illustrator", None, None, NO_ORACLE),
    ],
)
def test_classify_field_table(
    field: str,
    current_val: str | None,
    oracle_val: str | None,
    expected: str,
) -> None:
    assert classify_field(field, current_val, oracle_val) == expected


def test_diff_row_dataclass_shape() -> None:
    # Lightweight contract test: DiffRow fields are stable and writable.
    row = DiffRow(
        set_code="SV4A",
        local_id="001",
        field="rarity_code",
        current="SAR",
        oracle="SSR",
        classification=CONFLICT,
        source_url=None,
        is_manual=False,
    )
    assert row.classification == CONFLICT
    assert row.field == "rarity_code"
