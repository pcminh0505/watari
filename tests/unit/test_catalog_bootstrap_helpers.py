"""Unit tests for small pure helpers in ``pokeprice_catalog.bootstrap``.

Keeps the live pipeline untested (needs network), but anchors the
behaviour we care about for YML quality: variant-suffix stripping and
category inference.
"""

from __future__ import annotations

from pokeprice_catalog.bootstrap import (
    TcgdexCardMeta,
    _infer_category,
    _strip_variant_suffix_ja,
)


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
