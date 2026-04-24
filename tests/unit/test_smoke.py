"""Basic smoke test to verify test infrastructure works."""


def test_smoke():
    assert 1 + 1 == 2


def test_import_core():
    import watari_core  # noqa: F401
