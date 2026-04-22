"""Unit tests for canonical rarity mapping."""

from pokeprice_catalog.rarities import canonicalize_cardrush, canonicalize_tcgdex


class TestCardrush:
    def test_common(self):
        assert canonicalize_cardrush("C") == "C"

    def test_sar(self):
        assert canonicalize_cardrush("SAR") == "SAR"

    def test_ma(self):
        assert canonicalize_cardrush("MA") == "MA"

    def test_mur(self):
        assert canonicalize_cardrush("MUR") == "MUR"

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
