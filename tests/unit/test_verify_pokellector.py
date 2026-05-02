"""Unit tests for Pokellector vs disk local_id diff (no network)."""

from watari_catalog.verify_pokellector import diff_local_ids


def test_diff_local_ids_match() -> None:
    pk = {1, 2, 10}
    disk = {1, 2, 10}
    assert diff_local_ids(pk, disk) == ([], [])


def test_diff_local_ids_asymmetric() -> None:
    pk = {1, 2, 3}
    disk = {2, 3, 99}
    only_pk, only_disk = diff_local_ids(pk, disk)
    assert only_pk == [1]
    assert only_disk == [99]
