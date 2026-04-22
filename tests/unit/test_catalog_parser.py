"""Unit tests for the Cardrush product-name parser."""

from pokeprice_catalog.parser import parse_cardrush_product_name


class TestParseCardrushProductName:
    def test_trailing_rarity(self):
        r = parse_cardrush_product_name("ポケモンカード sv2a 163/165 ミュウツー ex SAR")
        assert r.set_code == "sv2a"
        assert r.local_id == "163"
        assert r.total == 165
        assert r.rarity_code == "SAR"
        assert r.variant == "normal"
        assert r.name_ja is not None and "ミュウツー" in r.name_ja

    def test_bracketed_rarity(self):
        r = parse_cardrush_product_name("【AR】ポケモンカード sv2a 054/165 ピカチュウ")
        assert r.set_code == "sv2a"
        assert r.local_id == "054"
        assert r.total == 165
        assert r.rarity_code == "AR"

    def test_master_ball_mirror_variant(self):
        r = parse_cardrush_product_name(
            "ポケモンカード sv2a 163/165 リザードン マスターボール柄 SAR"
        )
        assert r.variant == "master_ball_mirror"
        assert r.rarity_code == "SAR"
        assert r.local_id == "163"

    def test_mega_era_ma_rarity(self):
        r = parse_cardrush_product_name("ポケモンカード m2a 226/165 メガゲンガー MA")
        assert r.set_code == "m2a"
        assert r.local_id == "226"
        assert r.rarity_code == "MA"

    def test_bracket_code_fallback(self):
        r = parse_cardrush_product_name("【SAR】{163/165} リザードン")
        assert r.local_id == "163"
        assert r.total == 165
        assert r.rarity_code == "SAR"

    def test_common_single_letter_trailing(self):
        r = parse_cardrush_product_name("sv2a 054/165 ピカチュウ C")
        assert r.rarity_code == "C"

    def test_no_local_id_returns_none(self):
        r = parse_cardrush_product_name("ポケモンカード 拡張パック (未開封)")
        assert r.local_id is None
        assert r.set_code is None

    def test_empty_string(self):
        r = parse_cardrush_product_name("")
        assert r.local_id is None
        assert r.set_code is None
        assert r.variant == "normal"

    def test_name_ja_cleaned(self):
        r = parse_cardrush_product_name(
            "ポケモンカード sv2a 163/165 リザードンex ￥12,800 〔状態A〕 SAR"
        )
        assert r.name_ja is not None
        assert "￥" not in r.name_ja
        assert "SAR" not in r.name_ja
        assert "リザードン" in r.name_ja
