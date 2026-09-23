"""Einfaches Sprachsystem: Deutsch ist Quelltext, andere Sprachen kommen aus locales/<lang>.json.

Die Sprache wird einmal ganz am Anfang von setup.bat/setup.sh gewaehlt und in
``.runtime/language`` gespeichert. Die Starter reichen sie zusaetzlich als
``LLMBENCH_LANG`` weiter, damit auch der Docker-Container sie kennt. Ein
explizites ``project.language`` in benchmark.yaml hat Vorrang (siehe config.py).
"""

import json
import os
from pathlib import Path

SUPPORTED_LANGUAGES = ("de", "en")
DEFAULT_LANGUAGE = "de"
LANGUAGE_FILE = Path(".runtime") / "language"

_current_lang = DEFAULT_LANGUAGE
_translations: dict[str, str] = {}


def normalize_language(value: str | None) -> str | None:
    if not value:
        return None
    lang = value.strip().lower()[:2]
    return lang if lang in SUPPORTED_LANGUAGES else None


def detect_language(root: Path | str | None = None) -> str:
    """Sprache aus LLMBENCH_LANG, sonst aus .runtime/language, sonst Deutsch."""
    lang = normalize_language(os.environ.get("LLMBENCH_LANG"))
    if lang:
        return lang
    path = Path(root or ".") / LANGUAGE_FILE
    try:
        lang = normalize_language(path.read_text(encoding="utf-8-sig"))
    except OSError:
        lang = None
    return lang or DEFAULT_LANGUAGE


def save_language(lang: str, root: Path | str | None = None) -> None:
    path = Path(root or ".") / LANGUAGE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(lang + "\n", encoding="utf-8")


def language_preselected(root: Path | str | None = None) -> bool:
    """True, wenn die Sprache schon von einem Starter gewaehlt wurde."""
    if normalize_language(os.environ.get("LLMBENCH_LANG")):
        return True
    return (Path(root or ".") / LANGUAGE_FILE).is_file()


def current_language() -> str:
    return _current_lang


def set_language(lang: str):
    global _current_lang, _translations
    _current_lang = normalize_language(lang) or DEFAULT_LANGUAGE
    _translations = {}
    if _current_lang != DEFAULT_LANGUAGE:
        lang_file = Path(__file__).parent / "locales" / f"{_current_lang}.json"
        if lang_file.exists():
            with open(lang_file, encoding="utf-8") as f:
                _translations = json.load(f)


def _(text: str) -> str:
    if _current_lang == DEFAULT_LANGUAGE:
        return text
    return _translations.get(text, text)


set_language(detect_language())
