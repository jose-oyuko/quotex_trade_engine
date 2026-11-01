def test_pinned_pyquotex_is_importable() -> None:
    """Import only: proves the pinned git dependency installed on this Python. No network use."""
    import importlib.metadata

    import pyquotex  # noqa: F401

    assert importlib.metadata.version("pyquotex") == "1.1.0"
