"""Unit tests for variant slug detection."""

from watari_catalog.variants import detect_variant_from_cardrush_name


class TestDetectVariant:
    def test_no_marker_is_normal(self):
        assert detect_variant_from_cardrush_name("ポケモンカード sv2a 163/165 SAR") == "normal"

    def test_master_ball_pattern(self):
        assert (
            detect_variant_from_cardrush_name("sv2a 163/165 リザードン マスターボール柄 SAR")
            == "master_ball_mirror"
        )

    def test_poke_ball_mirror(self):
        assert (
            detect_variant_from_cardrush_name("sv2a 001 ピカチュウ モンスターボール柄")
            == "poke_ball_mirror"
        )

    def test_ultra_ball(self):
        assert (
            detect_variant_from_cardrush_name("sv2a 250 ハイパーボール柄")
            == "ultra_ball_mirror"
        )

    def test_quick_ball(self):
        assert (
            detect_variant_from_cardrush_name("sv2a 300 クイックボール柄")
            == "quick_ball_mirror"
        )

    def test_reverse_holo(self):
        assert (
            detect_variant_from_cardrush_name("sv2a 004 リバース")
            == "reverse_holo"
        )

    def test_jumbo(self):
        assert (
            detect_variant_from_cardrush_name("プロモ ジャンボ ミュウツー")
            == "jumbo"
        )

    def test_promo_fallback(self):
        assert detect_variant_from_cardrush_name("プロモカード 023") == "promo"

    def test_priority_master_ball_over_reverse(self):
        # When both markers appear, master-ball wins (more specific).
        name = "sv2a リザードン リバース マスターボール柄"
        assert detect_variant_from_cardrush_name(name) == "master_ball_mirror"
