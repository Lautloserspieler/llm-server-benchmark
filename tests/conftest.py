import pytest

from llmbench import i18n


@pytest.fixture(autouse=True)
def _german_by_default(monkeypatch):
    """Tests pruefen deutsche Texte - unabhaengig von einer lokal gewaehlten Sprache."""
    monkeypatch.setenv("LLMBENCH_LANG", "de")
    i18n.set_language("de")
    yield
    i18n.set_language("de")
