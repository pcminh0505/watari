"""Unit tests for card_id / artwork_id generation and parsing."""

import pytest
from pokeprice_core.catalog import (
    artwork_id_for_card,
    make_artwork_id,
    make_card_id,
    pad_local_id,
    parse_artwork_id,
    parse_card_id,
)


class TestPadLocalId:
    def test_numeric_pads_to_three(self):
        assert pad_local_id("7") == "007"

    def test_numeric_already_padded(self):
        assert pad_local_id("089") == "089"

    def test_numeric_four_digit_preserved(self):
        assert pad_local_id("1000") == "1000"

    def test_non_numeric_pass_through(self):
        assert pad_local_id("PR-001") == "PR-001"


class TestMakeCardId:
    def test_default_variant(self):
        assert make_card_id("SV2A", "89") == "jp-sv2a-089-normal"

    def test_explicit_variant(self):
        assert (
            make_card_id("sv2a", "163", "master_ball_mirror")
            == "jp-sv2a-163-master_ball_mirror"
        )

    def test_mega_dream(self):
        assert make_card_id("M2A", "226", "normal") == "jp-m2a-226-normal"

    def test_reverse_holo_variant(self):
        assert make_card_id("sv2a", "5", "reverse_holo") == "jp-sv2a-005-reverse_holo"


class TestParseCardId:
    def test_basic(self):
        assert parse_card_id("jp-sv2a-089-normal") == ("sv2a", "089", "normal")

    def test_multi_token_variant(self):
        assert parse_card_id("jp-sv2a-163-master_ball_mirror") == (
            "sv2a",
            "163",
            "master_ball_mirror",
        )

    def test_roundtrip(self):
        cid = make_card_id("sv2a", "1", "poke_ball_mirror")
        assert parse_card_id(cid) == ("sv2a", "001", "poke_ball_mirror")

    def test_invalid_prefix_raises(self):
        with pytest.raises(ValueError, match="Invalid card_id format"):
            parse_card_id("en-sv2a-089-normal")

    def test_missing_variant_raises(self):
        with pytest.raises(ValueError, match="Invalid card_id format"):
            parse_card_id("jp-sv2a-089")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="Invalid card_id format"):
            parse_card_id("")


class TestArtworkId:
    def test_make_artwork_id_pads_and_lowercases(self):
        assert make_artwork_id("SV2A", "89") == "jp-sv2a-089"

    def test_artwork_id_for_card(self):
        assert (
            artwork_id_for_card("jp-sv2a-163-master_ball_mirror") == "jp-sv2a-163"
        )

    def test_parse_artwork_id(self):
        assert parse_artwork_id("jp-sv2a-089") == ("sv2a", "089")

    def test_parse_artwork_id_invalid(self):
        with pytest.raises(ValueError):
            parse_artwork_id("sv2a-089")

    def test_card_has_matching_artwork(self):
        cid = make_card_id("sv2a", "89", "normal")
        assert artwork_id_for_card(cid) == make_artwork_id("sv2a", "89")
