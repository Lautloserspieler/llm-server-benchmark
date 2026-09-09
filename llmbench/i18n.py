import json
from pathlib import Path

_current_lang = "de"
_translations = {}

def set_language(lang: str):
    global _current_lang, _translations
    _current_lang = lang
    if lang != "de":
        lang_file = Path(__file__).parent / "locales" / f"{lang}.json"
        if lang_file.exists():
            with open(lang_file, "r", encoding="utf-8") as f:
                _translations = json.load(f)
        else:
            _translations = {}
    else:
        _translations = {}

def _(text: str) -> str:
    if _current_lang == "de":
        return text
    return _translations.get(text, text)
