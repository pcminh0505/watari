"""Unit tests for Cardrush run-layer helpers."""

from __future__ import annotations

from watari_cardrush.run import _CARDRUSH_PROMO_KEYWORD


class TestCardrushPromoKeywordMap:
    """Verify the promo-keyword map has correct entries."""

    def test_mp_keyword(self):
        assert _CARDRUSH_PROMO_KEYWORD["MP"] == "M-P"

    def test_smpr_keyword(self):
        assert _CARDRUSH_PROMO_KEYWORD["SMPR"] == "SM-P"

    def test_sp_keyword(self):
        assert _CARDRUSH_PROMO_KEYWORD["SP"] == "S-P"

    def test_svp_keyword(self):
        assert _CARDRUSH_PROMO_KEYWORD["SVP"] == "SV-P"

    def test_normal_set_not_in_map(self):
        assert "SV2A" not in _CARDRUSH_PROMO_KEYWORD

    def test_classic_set_not_in_map(self):
        assert "CLF" not in _CARDRUSH_PROMO_KEYWORD
        assert "CLL" not in _CARDRUSH_PROMO_KEYWORD
        assert "CLK" not in _CARDRUSH_PROMO_KEYWORD
