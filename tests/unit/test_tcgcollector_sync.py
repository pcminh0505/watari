"""Unit tests for ``watari_catalog.tcgcollector_sync``.

Fixtures are trimmed copies of the markup observed on
https://www.tcgcollector.com/sets/jp (image view) and on per-set pages in
``displayAs=list`` / ``displayAs=images`` mode (2026-09-27).
"""

from __future__ import annotations

import pathlib
from datetime import date

import pytest
import yaml
from watari_catalog import paths
from watari_catalog.bootstrap import TcgdexCardMeta
from watari_catalog.rarities import canonicalize_tcgcollector
from watari_catalog.seed_sets import _normalize
from watari_catalog.tcgcollector_sync import (
    TcgCollectorListCard,
    TcgCollectorSet,
    _sync_one_set,
    assign_set_codes,
    build_card_payload,
    category_from_card_type,
    dedupe_local_ids,
    local_id_from_number,
    normalize_code,
    official_total,
    parse_card_images,
    parse_set_card_list,
    parse_sets_page,
    resolve_tcgdex_ids,
    set_yaml_text,
    tcgdex_lookup,
)

SETS_PAGE = """
<h2>Mega Evolution Era</h2>
<div class="set-logo-grid-item set-search-result-item" data-set-id="11823">
  <div class="set-logo-grid-item-header">
    <img srcset="https://x/sym25.webp 25w, https://x/sym56.webp 56w"
         class="set-symbol set-logo-grid-item-symbol">
    <span class="set-logo-grid-item-name-container"><a
      href="/sets/11823/30th-celebration?setCardCountMode=anyCardVariant"
      class="set-logo-grid-item-name">30th Celebration</a><span
      class="set-logo-grid-item-code">M6a
      </span></span>
  </div>
  <div class="set-logo-grid-item-body">
    <a class="set-logo-grid-item-logo-container" href="/sets/11823/30th-celebration">
      <img srcset="https://x/logo250.webp 250w, https://x/logo400.webp 400w"
           class="set-logo-grid-item-logo">
    </a>
    <div class="set-logo-grid-item-release-date">
        Sep 16, 2026
    </div>
    <div class="progress"><div class="progress-label">0/176</div></div>
  </div>
</div>
<h2>Original Era</h2>
<div class="set-logo-grid-item set-search-result-item" data-set-id="11182">
  <div class="set-logo-grid-item-header">
    <span class="set-logo-grid-item-name-container"><a
      href="/sets/11182/expansion-pack?setCardCountMode=anyCardVariant"
      class="set-logo-grid-item-name">Expansion Pack</a></span>
  </div>
  <div class="set-logo-grid-item-body">
    <div class="set-logo-grid-item-release-date">Oct 20, 1996</div>
    <div class="progress"><div class="progress-label">0/102</div></div>
  </div>
</div>
"""

CARD_LIST_PAGE = """
<div class="card-list-item card-search-result-item" data-card-id="89737">
  <div class="card-list-item-entry card-list-item-number-entry">001/103</div>
  <a href="/cards/89737/exeggcute-30th-celebration-001-103"
     class="card-list-item-entry card-list-item-name-entry">Exeggcute</a>
  <div class="card-list-item-entry card-list-item-card-type-entry">
    <img alt="Grass" title="Grass" class="energy-type-symbol">
  </div>
  <div class="card-list-item-entry card-list-item-rarity-entry">
    <img alt="Common (C)" title="Common (C)">
  </div>
</div>
<div class="card-list-item card-search-result-item" data-card-id="89900">
  <div class="card-list-item-entry card-list-item-number-entry">No. 174</div>
  <a class="card-list-item-entry card-list-item-name-entry">Basic Fighting Energy</a>
  <div class="card-list-item-entry card-list-item-card-type-entry">Energy</div>
  <div class="card-list-item-entry card-list-item-rarity-entry">—</div>
</div>
<div class="card-list-item card-search-result-item" data-card-id="89737">
  <div class="card-list-item-entry card-list-item-number-entry">001/103</div>
  <a class="card-list-item-entry card-list-item-name-entry">Exeggcute</a>
</div>
"""

CARD_IMAGES_PAGE = """
<div id="card-image-grid">
  <div class="card-image-grid-item">
    <a class="card-image-grid-item-link" href="/cards/89737/exeggcute-30th-celebration-001-103">
      <img class="card-image-grid-item-image"
           srcset="https://x/c1-small.webp 200w, https://x/c1-large.webp 400w">
    </a>
  </div>
  <div class="card-image-grid-item">
    <a class="card-image-grid-item-link" href="/cards/29985/bulbasaur-expansion-pack-no-001">
      <img class="card-image-grid-item-image" src="https://x/c2.webp">
    </a>
  </div>
</div>
"""


def _set(
    tcgc_id: str,
    code: str | None,
    *,
    era: str = "sw",
    released: date = date(2020, 1, 1),
) -> TcgCollectorSet:
    return TcgCollectorSet(
        tcgcollector_id=tcgc_id,
        slug=f"set-{tcgc_id}",
        name_en=f"Set {tcgc_id}",
        code=code,
        era_block=era,
        release_date=released,
        card_count=10,
        logo_url=None,
        symbol_url=None,
    )


def _card(local_id: str, denominator: str | None = None) -> TcgCollectorListCard:
    return TcgCollectorListCard(
        card_id=f"c{local_id}",
        number_raw=local_id,
        local_id=local_id,
        denominator=denominator,
        name_en="X",
        rarity_raw=None,
        card_type=None,
    )


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_parse_sets_page_reads_era_code_date_count_and_artwork() -> None:
    sets = parse_sets_page(SETS_PAGE)

    assert [s.tcgcollector_id for s in sets] == ["11823", "11182"]
    m6a, base = sets
    assert m6a.slug == "30th-celebration"
    assert m6a.name_en == "30th Celebration"
    assert m6a.code == "M6a"
    assert m6a.era_block == "me"
    assert m6a.release_date == date(2026, 9, 16)
    assert m6a.card_count == 176
    assert m6a.logo_url == "https://x/logo400.webp"
    assert m6a.symbol_url == "https://x/sym56.webp"

    assert base.code is None
    assert base.era_block == "original"
    assert base.release_date == date(1996, 10, 20)
    assert base.logo_url is None


def test_parse_sets_page_rejects_sets_under_unknown_era() -> None:
    html = SETS_PAGE.replace("<h2>Original Era</h2>", "<h2>Brand New Era</h2>")
    with pytest.raises(ValueError, match="Brand New Era"):
        parse_sets_page(html)


def test_parse_sets_page_ignores_unknown_heading_without_sets() -> None:
    sets = parse_sets_page("<h2>Newsletter</h2>" + SETS_PAGE)
    assert len(sets) == 2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("001/103", ("001", "103")),
        ("No. 7", ("007", None)),
        ("No. 1234", ("1234", None)),
        ("12/20", ("012", "20")),
        ("015/XY-P", ("015", "XY-P")),
        ("R/RGB", ("R", "RGB")),
    ],
)
def test_local_id_from_number(raw: str, expected: tuple[str, str | None]) -> None:
    assert local_id_from_number(raw) == expected


def test_local_id_from_number_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        local_id_from_number("??")


def test_parse_set_card_list_extracts_fields_and_dedupes() -> None:
    cards = parse_set_card_list(CARD_LIST_PAGE)

    assert [c.card_id for c in cards] == ["89737", "89900"]
    exeggcute, energy = cards
    assert exeggcute.local_id == "001"
    assert exeggcute.denominator == "103"
    assert exeggcute.name_en == "Exeggcute"
    assert exeggcute.rarity_raw == "Common (C)"
    assert exeggcute.card_type == "Grass"
    assert energy.local_id == "174"
    assert energy.rarity_raw is None
    assert energy.card_type == "Energy"


def test_parse_card_images_keys_by_card_id_and_prefers_widest() -> None:
    assert parse_card_images(CARD_IMAGES_PAGE) == {
        "89737": "https://x/c1-large.webp",
        "29985": "https://x/c2.webp",
    }


# ---------------------------------------------------------------------------
# Codes + TCGdex ids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [("M6a", "M6A"), ("S8a-G", "S8AG"), ("HS+", "HSP"), ("K+K", "KPK"), (None, "")],
)
def test_normalize_code(code: str | None, expected: str) -> None:
    assert normalize_code(code) == expected


def test_assign_set_codes_rules() -> None:
    unique = _set("1", "S8a-G")
    shared_a = _set("2", "SA", released=date(2019, 11, 29))
    shared_b = _set("3", "SA", released=date(2019, 11, 29))
    clash = _set("4", "MP", era="other")  # our MP is a different set
    codeless_1 = _set("5", None, era="original", released=date(1998, 1, 1))
    codeless_2 = _set("6", None, era="original", released=date(1997, 1, 1))
    on_tcgdex = _set("7", None, era="original", released=date(1996, 10, 20))
    missing = [unique, shared_a, shared_b, clash, codeless_1, codeless_2, on_tcgdex]
    existing_mp = _set("99", "MP", era="me")

    codes = assign_set_codes(
        missing,
        all_sets=[*missing, existing_mp],
        existing_codes={"MP", "SV2A"},
        tcgdex_ids={"7": "PMCG1"},
    )

    assert codes == {
        "1": "S8AG",
        "2": "SAA",
        "3": "SAB",
        "4": "MPA",
        "6": "ORX01",  # older release claims the first generated slot
        "5": "ORX02",
        "7": "PMCG1",
    }


def test_assign_set_codes_skips_taken_generated_codes() -> None:
    codes = assign_set_codes(
        [_set("5", None, era="original")],
        all_sets=[],
        existing_codes={"ORX01"},
        tcgdex_ids={},
    )
    assert codes == {"5": "ORX02"}


def test_resolve_tcgdex_ids_curated_code_match_and_exclusions() -> None:
    curated = _set("11182", None, era="original")  # Expansion Pack → PMCG1
    code_match = _set("11823", "M6a", era="me")
    shared = [_set("20", "L2"), _set("21", "L2")]
    already_used = _set("30", "M6", era="me")

    ids = resolve_tcgdex_ids(
        [curated, code_match, *shared, already_used],
        {"PMCG1", "M6a", "L2", "M6"},
        used={"M6"},
    )

    assert ids == {"11182": "PMCG1", "11823": "M6a"}


# ---------------------------------------------------------------------------
# Card + set assembly
# ---------------------------------------------------------------------------


def test_official_total_uses_majority_numeric_denominator() -> None:
    cards = [_card("001", "103"), _card("002", "103"), _card("R", "RGB")]
    assert official_total(cards) == 103
    assert official_total([_card("001"), _card("002"), _card("003", "10")]) is None


def test_dedupe_local_ids_suffixes_repeats() -> None:
    pairs = dedupe_local_ids([_card("001"), _card("001"), _card("002")])
    assert [local_id for local_id, _ in pairs] == ["001", "001B", "002"]


@pytest.mark.parametrize(
    ("card_type", "expected"),
    [("Trainer", "trainer"), ("Energy", "energy"), ("Grass", "card"), (None, "card")],
)
def test_category_from_card_type(card_type: str | None, expected: str) -> None:
    assert category_from_card_type(card_type) == expected


def test_tcgdex_lookup_handles_padded_and_bare_keys() -> None:
    meta = TcgdexCardMeta(
        local_id="7", name_ja="x", rarity_raw=None, illustrator=None, category=None
    )
    assert tcgdex_lookup({"7": meta}, "007") is meta
    assert tcgdex_lookup({"007": meta}, "007") is meta
    assert tcgdex_lookup({"7": meta}, "R") is None


def test_build_card_payload_prefers_tcgdex_for_ja_fields() -> None:
    card = TcgCollectorListCard(
        card_id="89737",
        number_raw="063/103",
        local_id="063",
        denominator="103",
        name_en="Legendary Summit",
        rarity_raw=None,
        card_type="Grass",
    )
    tcgdex = TcgdexCardMeta(
        local_id="063",
        name_ja="伝説の山頂",
        rarity_raw="Uncommon",
        illustrator="nagimiso",
        category="trainer",
    )

    payload = build_card_payload(
        set_code="M6A", local_id="063", card=card, image_url="https://x/i.webp", tcgdex=tcgdex
    )

    assert payload.name_ja == "伝説の山頂"
    assert payload.name_en == "Legendary Summit"
    assert payload.rarity_code == "U"  # TCGCollector has none → TCGdex
    assert payload.category == "trainer"
    assert payload.illustrator == "nagimiso"
    assert payload.prints == ["normal"]
    assert payload.sources == {
        "tcgcollector": {"id": "89737", "rarity_raw": None},
        "tcgdex": {"id": "063", "rarity_raw": "Uncommon"},
    }


def test_set_yaml_text_round_trips_through_seed_sets(tmp_path: pathlib.Path) -> None:
    s = TcgCollectorSet(
        tcgcollector_id="11455",
        slug="25th-anniversary-golden-box",
        name_en="25th Anniversary Golden Box",
        code="S8a-G",
        era_block="sw",
        release_date=date(2021, 12, 1),
        card_count=16,
        logo_url="https://x/logo.webp",
        symbol_url="https://x/sym.webp",
    )
    path = tmp_path / "S8AG.yml"
    path.write_text(
        set_yaml_text(s, set_code="S8AG", name_ja=None, total=None, tcgdex_id=None),
        encoding="utf-8",
    )

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["release_date"] == date(2021, 12, 1)
    assert raw["tcgcollector_id"] == "11455"
    assert raw["name_ja"] is None

    row = _normalize(raw, source_path=path)
    assert row["set_code"] == "S8AG"
    assert row["era_block"] == "sw"
    assert row["source_refs"]["tcgcollector"] == {
        "id": "11455",
        "slug": "25th-anniversary-golden-box",
        "code": "S8a-G",
    }
    assert row["source_refs"]["logo_url"] == "https://x/logo.webp"
    assert row["source_refs"]["symbol_url"] == "https://x/sym.webp"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Rare Holo", "R"),
        ("Rare Holo ex", "RR"),
        ("Rare Holo LV.X", "RR"),
        ("Rare Prime", "RR"),
        ("Rare Holo ☆", "UR"),
        ("LEGEND", "UR"),
        ("Pikachu Rare", None),  # 30th Celebration tier: no canonical code yet
    ],
)
def test_legacy_tcgcollector_rarities(raw: str, expected: str | None) -> None:
    assert canonicalize_tcgcollector(raw) == expected


# ---------------------------------------------------------------------------
# _sync_one_set (pages faked, data dir redirected to tmp_path)
# ---------------------------------------------------------------------------


class _FakePages:
    def __init__(self, list_html: str, images_html: str) -> None:
        self._pages = {"list": list_html, "images": images_html}

    async def set_page(self, s: TcgCollectorSet, display: str) -> str:
        return self._pages[display]


@pytest.fixture
def data_root(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    (tmp_path / "sets").mkdir()
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    return tmp_path


def _m6a(card_count: int | None) -> TcgCollectorSet:
    return TcgCollectorSet(
        tcgcollector_id="11823",
        slug="30th-celebration",
        name_en="30th Celebration",
        code="M6a",
        era_block="me",
        release_date=date(2026, 9, 16),
        card_count=card_count,
        logo_url=None,
        symbol_url=None,
    )


async def test_sync_one_set_writes_cards_then_set(data_root: pathlib.Path) -> None:
    emit = await _sync_one_set(
        _m6a(2),
        set_code="M6A",
        pages=_FakePages(CARD_LIST_PAGE, CARD_IMAGES_PAGE),  # type: ignore[arg-type]
        tcgdex_id=None,
        tcgdex_name=None,
        bronze=None,
    )

    assert emit.written == 2
    assert sorted(p.name for p in (data_root / "cards" / "M6A").iterdir()) == ["001.yml", "174.yml"]
    card = yaml.safe_load((data_root / "cards" / "M6A" / "001.yml").read_text(encoding="utf-8"))
    assert card["image"] == "https://x/c1-large.webp"
    assert card["rarity_code"] == "C"
    energy = yaml.safe_load((data_root / "cards" / "M6A" / "174.yml").read_text(encoding="utf-8"))
    assert energy["category"] == "energy"
    set_doc = yaml.safe_load((data_root / "sets" / "M6A.yml").read_text(encoding="utf-8"))
    assert set_doc["tcgcollector_id"] == "11823"
    assert set_doc["total"] == 103


async def test_sync_one_set_fails_on_empty_page_without_marking_synced(
    data_root: pathlib.Path,
) -> None:
    with pytest.raises(RuntimeError, match="0 cards"):
        await _sync_one_set(
            _m6a(176),
            set_code="M6A",
            pages=_FakePages("<html>Just a moment...</html>", ""),  # type: ignore[arg-type]
            tcgdex_id=None,
            tcgdex_name=None,
            bronze=None,
        )
    assert not (data_root / "sets" / "M6A.yml").exists()


async def test_sync_one_set_allows_sets_listed_with_no_cards(data_root: pathlib.Path) -> None:
    emit = await _sync_one_set(
        _m6a(None),  # e.g. SX01: TCGCollector shows no card count
        set_code="SX01",
        pages=_FakePages("<html></html>", ""),  # type: ignore[arg-type]
        tcgdex_id=None,
        tcgdex_name=None,
        bronze=None,
    )
    assert emit.written == 0
    assert (data_root / "sets" / "SX01.yml").exists()
