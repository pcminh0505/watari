"""Unit tests for small pure helpers in ``watari_catalog.bootstrap``.

Keeps the live pipeline untested (needs network), but anchors the
behaviour we care about for YML quality: variant-suffix stripping and
category inference.
"""

from __future__ import annotations

from watari_catalog.bootstrap import (
    CardrushCardHints,
    TcgdexCardMeta,
    _choose_rarity,
    _infer_category,
    _prefer_cardrush_rarity,
    _strip_variant_suffix_ja,
)
from watari_catalog.pokellector_client import PokellectorCardDetail


class TestStripVariantSuffixJa:
    def test_strips_masterball_mirror(self):
        assert _strip_variant_suffix_ja("ベトベトン(マスターボールミラー)") == "ベトベトン"

    def test_strips_monsterball_mirror(self):
        assert (
            _strip_variant_suffix_ja("ミュウツー(モンスターボールミラー)") == "ミュウツー"
        )

    def test_strips_fullwidth_parens(self):
        assert (
            _strip_variant_suffix_ja("ミュウツー(マスターボールミラー)") == "ミュウツー"
        )

    def test_passthrough_when_no_suffix(self):
        assert _strip_variant_suffix_ja("ベトベトン") == "ベトベトン"

    def test_none_is_noop(self):
        assert _strip_variant_suffix_ja(None) is None

    def test_empty_is_noop(self):
        assert _strip_variant_suffix_ja("") == ""

    def test_leaves_unrelated_parens(self):
        # We only strip the known variant-qualifier set; other parens stay.
        assert _strip_variant_suffix_ja("ピカチュウ(テラスタル)") == "ピカチュウ(テラスタル)"


class TestInferCategory:
    def test_tcgdex_category_wins(self):
        tcg = TcgdexCardMeta(
            local_id="1",
            name_ja="マリィ",
            rarity_raw=None,
            illustrator=None,
            category="trainer",
        )
        assert _infer_category(tcgdex=tcg, name_ja="マリィ", name_en="Marnie") == "trainer"

    def test_infers_trainer_from_ja_keyword(self):
        assert (
            _infer_category(tcgdex=None, name_ja="ハイパーボール", name_en="Hyper Ball")
            == "card"
        )
        assert (
            _infer_category(tcgdex=None, name_ja="サポート: マリィ", name_en="Marnie")
            == "trainer"
        )

    def test_infers_energy(self):
        assert (
            _infer_category(tcgdex=None, name_ja="基本炎エネルギー", name_en="Basic Fire Energy")
            == "energy"
        )

    def test_default_is_card(self):
        assert _infer_category(tcgdex=None, name_ja="ピカチュウ", name_en="Pikachu") == "card"


class TestPreferCardrushRarity:
    def test_rr_beats_r(self):
        assert _prefer_cardrush_rarity("R", "RR") == "RR"
        assert _prefer_cardrush_rarity("RR", "R") == "RR"

    def test_rr_beats_first_hit_ur(self):
        assert _prefer_cardrush_rarity("UR", "RR") == "RR"

    def test_sr_beats_rr_when_incoming_higher(self):
        assert _prefer_cardrush_rarity("RR", "SR") == "SR"


class TestChooseRarityLegacyUltraMiscast:
    def test_sm_prefers_rr_from_cardrush(self):
        p = PokellectorCardDetail("1", "Ultra Rare", "10/098")
        h = CardrushCardHints(None, frozenset({"normal"}), "RR")
        assert (
            _choose_rarity(
                era_block="sm",
                name_en="Buzzwole GX",
                pokellector=p,
                tcgdex=None,
                cardrush=h,
            )
            == "RR"
        )

    def test_sw_respects_cardrush_sr_over_ultra_miscast(self):
        p = PokellectorCardDetail("1", "Ultra Rare", None)
        h = CardrushCardHints(None, frozenset({"normal"}), "SR")
        assert (
            _choose_rarity(
                era_block="sw",
                name_en="Trainer full art",
                pokellector=p,
                tcgdex=None,
                cardrush=h,
            )
            == "SR"
        )

    def test_heuristic_rr_pokemon_v_when_no_cardrush_hint(self):
        p = PokellectorCardDetail("25", "Ultra Rare", "25/098")
        h = CardrushCardHints(None, frozenset({"normal"}), None)
        assert (
            _choose_rarity(
                era_block="sw",
                name_en="Pikachu V",
                pokellector=p,
                tcgdex=None,
                cardrush=h,
            )
            == "RR"
        )

    def test_secret_collector_keeps_mapped_ultra(self):
        p = PokellectorCardDetail("104", "Ultra Rare", "104/069")
        h = CardrushCardHints(None, frozenset({"normal"}), None)
        assert (
            _choose_rarity(
                era_block="sw",
                name_en="Charizard VMAX",
                pokellector=p,
                tcgdex=None,
                cardrush=h,
            )
            == "UR"
        )
