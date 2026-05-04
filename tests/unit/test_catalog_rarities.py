"""Unit tests for canonical rarity mapping."""

import pytest
from watari_catalog.rarities import (
    canonicalize_cardrush,
    canonicalize_pokellector,
    canonicalize_tcgcollector,
    canonicalize_tcgdex,
)


class TestCardrush:
    def test_common(self):
        assert canonicalize_cardrush("C") == "C"

    def test_sar(self):
        assert canonicalize_cardrush("SAR") == "SAR"

    def test_ma(self):
        assert canonicalize_cardrush("MA") == "MA"

    def test_mur(self):
        assert canonicalize_cardrush("MUR") == "MUR"

    def test_shiny(self):
        assert canonicalize_cardrush("S") == "S"

    def test_lowercase_ok(self):
        assert canonicalize_cardrush("sar") == "SAR"

    def test_unknown_returns_none(self):
        assert canonicalize_cardrush("ZZZ") is None

    def test_empty_returns_none(self):
        assert canonicalize_cardrush("") is None
        assert canonicalize_cardrush(None) is None


class TestTcgdex:
    def test_common(self):
        assert canonicalize_tcgdex("Common") == "C"

    def test_double_rare(self):
        assert canonicalize_tcgdex("Double rare") == "RR"

    def test_sar(self):
        assert canonicalize_tcgdex("Special illustration rare") == "SAR"

    def test_unknown_returns_none(self):
        assert canonicalize_tcgdex("Future Rarity 9000") is None
        assert canonicalize_tcgdex(None) is None


class TestPokellector:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Common", "C"),
            ("Uncommon", "U"),
            ("Rare", "R"),
            ("Ultra Rare", "UR"),
            ("Super Rare", "SR"),
            ("Art Rare", "AR"),
            ("Special Art Rare", "SAR"),
            ("Hyper Rare", "HR"),
            # SM-era labels added in Pillar 1
            ("Secret Rare", "UR"),
            ("Prism Star", "SR"),
            # Shiny tier (baby shinies — SV4A, S4A)
            ("Shiny", "S"),
            ("Shiny Rare", "S"),
            # ME-era
            ("Master Ball Rare", "MA"),
            ("Masterball Rare", "MA"),
            # SV-era jp.pokellector.com labels
            ("Ace Spec", "R"),
            ("Super Secret Rare", "SAR"),
            ("B Double Rare", "RR"),
        ],
    )
    def test_known_labels(self, raw: str, expected: str) -> None:
        assert canonicalize_pokellector(raw) == expected

    def test_unknown_returns_none(self) -> None:
        assert canonicalize_pokellector("GoldenRareXX") is None

    def test_none_returns_none(self) -> None:
        assert canonicalize_pokellector(None) is None

    def test_strips_whitespace(self) -> None:
        assert canonicalize_pokellector("  Secret Rare  ") == "UR"


class TestTcgCollector:
    """TCGCollector publishes rarity in three flavours; all roads lead home."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            # 1. English label with parenthesised canonical code (most common)
            ("Common (C)", "C"),
            ("Uncommon (U)", "U"),
            ("Rare (R)", "R"),
            ("Double Rare (RR)", "RR"),
            ("Art Rare (AR)", "AR"),
            ("Special Art Rare (SAR)", "SAR"),
            ("Ultra Rare (UR)", "UR"),
            ("Hyper Rare (HR)", "HR"),
            # The parenthesised code wins even if our label map disagrees.
            ("Some Future Rarity (SAR)", "SAR"),
        ],
    )
    def test_extracts_parenthesised_code(self, raw: str, expected: str) -> None:
        assert canonicalize_tcgcollector(raw) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Common", "C"),
            ("Uncommon", "U"),
            ("Rare", "R"),
            ("Double Rare", "RR"),
            ("Art Rare", "AR"),
            ("Super Rare", "SR"),
            ("Special Art Rare", "SAR"),
            ("Ultra Rare", "UR"),
            ("Hyper Rare", "HR"),
            ("Shiny Rare", "S"),
            ("Shiny Ultra Rare", "SSR"),
            ("Shiny Super Rare", "SSR"),
            ("Amazing Rare", "RRR"),
            ("Radiant Rare", "K"),
            ("Character Rare", "CHR"),
            ("Character Super Rare", "CSR"),
            ("Trainer Gallery Rare Holo", "TR"),
            ("ACE SPEC Rare", "R"),
            ("Master Ball Rare", "MA"),
            ("Masterball Rare", "MA"),
            ("Prism Star", "SR"),
        ],
    )
    def test_english_label_only(self, raw: str, expected: str) -> None:
        assert canonicalize_tcgcollector(raw) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("コモン", "C"),
            ("アンコモン", "U"),
            ("レア", "R"),
            ("ダブルレア", "RR"),
            ("ウルトラレア", "UR"),
            ("アートレア", "AR"),
            ("スペシャルアートレア", "SAR"),
            ("ハイパーレア", "HR"),
            ("シャイニーレア", "S"),
            ("シャイニースーパーレア", "SSR"),
            ("アメイジングレア", "RRR"),
            ("キャラクターレア", "CHR"),
            ("キャラクタースーパーレア", "CSR"),
            ("ラディアントレア", "K"),
            ("マスターボールレア", "MA"),
        ],
    )
    def test_native_japanese_labels(self, raw: str, expected: str) -> None:
        assert canonicalize_tcgcollector(raw) == expected

    def test_unknown_returns_none(self) -> None:
        assert canonicalize_tcgcollector("Future Mystery Rare") is None
        assert canonicalize_tcgcollector("ぴかぴかレア") is None

    def test_empty_returns_none(self) -> None:
        assert canonicalize_tcgcollector("") is None
        assert canonicalize_tcgcollector(None) is None

    def test_strips_whitespace(self) -> None:
        assert canonicalize_tcgcollector("  Common (C)  ") == "C"
        assert canonicalize_tcgcollector("  Common  ") == "C"

    def test_lowercase_parens_code_falls_through_to_label(self) -> None:
        # Parens code must be uppercase / canonical-looking. ``(c)`` is
        # ignored, but the label itself is still resolved.
        assert canonicalize_tcgcollector("Common (c)") == "C"

    def test_long_parens_token_is_ignored(self) -> None:
        # Parens-token longer than 4 letters (e.g. a phrase, not a code)
        # falls through to label match. Here the label still resolves.
        assert canonicalize_tcgcollector("Common (regular)") == "C"
