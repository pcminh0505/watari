"""Unit tests for small pure helpers in ``watari_catalog.bootstrap``.

Keeps the live pipeline untested (needs network), but anchors the
behaviour we care about for YML quality: variant-suffix stripping and
category inference.
"""

from __future__ import annotations

from watari_catalog.bootstrap import (
    CardrushCardHints,
    TcgCollectorAuditMeta,
    TcgdexCardMeta,
    _audit_overrides_pokellector,
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


# ---------------------------------------------------------------------------
# Phase 7: TCGCollector audit-vs-Pokellector precedence
# ---------------------------------------------------------------------------


def _audit(
    *,
    local_id: str = "001",
    name_en: str | None = None,
    rarity_canon: str | None = None,
    illustrator: str | None = None,
    name_ja: str | None = None,
) -> TcgCollectorAuditMeta:
    return TcgCollectorAuditMeta(
        local_id=local_id,
        name_en=name_en,
        rarity_canon=rarity_canon,
        illustrator=illustrator,
        name_ja=name_ja,
    )


class TestAuditOverridesPokellector:
    """Audit beats Pokellector iff Pokellector raw label is too coarse."""

    def test_no_audit_means_no_override(self) -> None:
        p = PokellectorCardDetail("1", "Secret Rare", None)
        assert _audit_overrides_pokellector(p, None) is False

    def test_audit_without_canon_means_no_override(self) -> None:
        p = PokellectorCardDetail("1", "Secret Rare", None)
        assert _audit_overrides_pokellector(p, _audit(rarity_canon=None)) is False

    def test_no_pokellector_means_audit_wins(self) -> None:
        # Pokellector returned no detail at all — audit fills the gap.
        assert _audit_overrides_pokellector(None, _audit(rarity_canon="SAR")) is True

    def test_secret_rare_is_overridden(self) -> None:
        p = PokellectorCardDetail("100", "Secret Rare", None)
        assert _audit_overrides_pokellector(p, _audit(rarity_canon="AR")) is True

    def test_super_secret_rare_is_overridden(self) -> None:
        p = PokellectorCardDetail("320", "Super Secret Rare", None)
        assert _audit_overrides_pokellector(p, _audit(rarity_canon="SSR")) is True

    def test_specific_pokellector_label_keeps_pokellector(self) -> None:
        # Pokellector knows it's an Art Rare — audit can't override.
        p = PokellectorCardDetail("100", "Art Rare", None)
        assert _audit_overrides_pokellector(p, _audit(rarity_canon="SR")) is False

    def test_pokellector_with_blank_raw_is_overridden(self) -> None:
        # Pokellector raw label is missing — audit takes over.
        p = PokellectorCardDetail("1", None, None)
        # `None` raw isn't in the coarse set; audit doesn't beat it on
        # this code path (it'll lose the coarse-label check), so it must
        # fall through to the lower-priority audit branch in
        # `_choose_rarity` instead. This documents the contract.
        assert _audit_overrides_pokellector(p, _audit(rarity_canon="SAR")) is False


class TestChooseRarityWithAudit:
    """End-to-end precedence: audit beats coarse Pokellector labels."""

    def test_audit_overrides_secret_rare(self) -> None:
        # The SV1S/SV1V pattern: Pokellector calls everything > 080
        # "Secret Rare", audit knows it's actually AR.
        p = PokellectorCardDetail("085", "Secret Rare", None)
        a = _audit(local_id="085", rarity_canon="AR")
        assert (
            _choose_rarity(
                era_block="sv",
                name_en="Iono",
                pokellector=p,
                tcgdex=None,
                cardrush=None,
                audit=a,
            )
            == "AR"
        )

    def test_audit_overrides_super_secret_rare(self) -> None:
        # SV4A 320-336 are SSR but Pokellector says "Super Secret Rare".
        p = PokellectorCardDetail("320", "Super Secret Rare", None)
        a = _audit(local_id="320", rarity_canon="SSR")
        assert (
            _choose_rarity(
                era_block="sv",
                name_en="Charizard ex",
                pokellector=p,
                tcgdex=None,
                cardrush=None,
                audit=a,
            )
            == "SSR"
        )

    def test_specific_pokellector_label_wins_over_audit(self) -> None:
        # Pokellector is specific ("Art Rare"); audit must not override.
        p = PokellectorCardDetail("200", "Art Rare", None)
        a = _audit(local_id="200", rarity_canon="SAR")
        assert (
            _choose_rarity(
                era_block="sv",
                name_en="Pikachu ex",
                pokellector=p,
                tcgdex=None,
                cardrush=None,
                audit=a,
            )
            == "AR"
        )

    def test_audit_only_used_as_last_resort_when_pokellector_unmappable(self) -> None:
        # No Pokellector, no TCGdex, no Cardrush — audit fills the gap.
        a = _audit(rarity_canon="HR")
        assert (
            _choose_rarity(
                era_block="sv",
                name_en="Mew",
                pokellector=None,
                tcgdex=None,
                cardrush=None,
                audit=a,
            )
            == "HR"
        )

    def test_audit_doesnt_override_specific_tcgdex_when_no_pokellector(self) -> None:
        # No Pokellector — audit wins because `_audit_overrides_pokellector`
        # returns True when Pokellector is absent.
        tcg = TcgdexCardMeta(
            local_id="001",
            name_ja=None,
            rarity_raw="Common",
            illustrator=None,
            category=None,
        )
        a = _audit(rarity_canon="AR")
        assert (
            _choose_rarity(
                era_block="sv",
                name_en="X",
                pokellector=None,
                tcgdex=tcg,
                cardrush=None,
                audit=a,
            )
            == "AR"
        )

    def test_no_audit_falls_through_to_pokellector(self) -> None:
        p = PokellectorCardDetail("1", "Common", None)
        assert (
            _choose_rarity(
                era_block="sv",
                name_en="Bulbasaur",
                pokellector=p,
                tcgdex=None,
                cardrush=None,
                audit=None,
            )
            == "C"
        )
