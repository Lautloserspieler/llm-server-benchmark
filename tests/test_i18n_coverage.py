"""Stellt sicher, dass das Sprachsystem vollstaendig bleibt.

Jeder neue nutzersichtbare Text muss in allen Sprachen vorhanden sein - sowohl
im Python-Paket (``_()`` + ``llmbench/locales/en.json``) als auch in den
Installer-Skripten (``scripts/locales``).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from llmbench import i18n

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "llmbench"
SCRIPT_LOCALES = ROOT / "scripts" / "locales"


def _translation_calls() -> list[tuple[Path, int, ast.expr | None]]:
    calls = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_":
                calls.append((path, node.lineno, node.args[0] if node.args else None))
    return calls


def test_translation_calls_use_plain_string_literals():
    # _(f"...") oder _(variable) kann nicht uebersetzt werden; Platzhalter
    # gehoeren in den Text und werden danach mit .format() gefuellt.
    bad = [
        f"{path.relative_to(ROOT)}:{line}"
        for path, line, arg in _translation_calls()
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str))
    ]
    assert not bad, "Nicht-literale _()-Aufrufe: " + ", ".join(bad)


def test_no_function_shadows_the_translator():
    # `x, _ = ...` macht `_` in der ganzen Funktion lokal - ein `_("...")` in
    # derselben Funktion wuerde dann nicht mehr uebersetzen, sondern abstuerzen.
    bad = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            nodes = list(ast.walk(func))
            assigns = any(isinstance(n, ast.Name) and n.id == "_" and isinstance(n.ctx, ast.Store) for n in nodes)
            calls = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_" for n in nodes)
            if assigns and calls:
                bad.append(f"{path.relative_to(ROOT)}:{func.lineno} {func.name}")
    assert not bad, "Funktionen ueberschreiben _ und rufen _() auf: " + ", ".join(bad)


def test_every_translated_python_string_has_english_entry():
    english = json.loads((PACKAGE / "locales" / "en.json").read_text(encoding="utf-8"))
    missing = sorted(
        {
            f"{path.relative_to(ROOT)}:{line}: {arg.value!r}"
            for path, line, arg in _translation_calls()
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value not in english
        }
    )
    assert not missing, "Fehlende Eintraege in llmbench/locales/en.json:\n" + "\n".join(missing)


def test_english_entries_keep_format_placeholders():
    english = json.loads((PACKAGE / "locales" / "en.json").read_text(encoding="utf-8"))
    placeholder = re.compile(r"\{[a-zA-Z_0-9]*\}")
    wrong = [
        key
        for key, value in english.items()
        if sorted(placeholder.findall(key)) != sorted(placeholder.findall(value)) or not value.strip()
    ]
    assert not wrong, "Platzhalter/leere Werte stimmen nicht: " + ", ".join(wrong)


def _psd1_keys(path: Path) -> dict[str, str]:
    return dict(re.findall(r"^\s*'([^']+)'\s*=\s*'((?:[^']|'')*)'", path.read_text(encoding="utf-8-sig"), re.M))


def _sh_keys(path: Path) -> dict[str, str]:
    return dict(re.findall(r'^\s*\[([A-Za-z0-9_.]+)\]="((?:[^"\\]|\\.)*)"', path.read_text(encoding="utf-8"), re.M))


@pytest.mark.parametrize(("suffix", "parser"), [("psd1", _psd1_keys), ("sh", _sh_keys)])
def test_script_locales_have_identical_keys(suffix, parser):
    de = parser(SCRIPT_LOCALES / f"de.{suffix}")
    en = parser(SCRIPT_LOCALES / f"en.{suffix}")
    assert de, f"de.{suffix} enthaelt keine Texte"
    assert set(de) == set(en), f"Unterschiedliche Keys in de/en.{suffix}: {sorted(set(de) ^ set(en))}"
    placeholder = re.compile(r"\{\d+\}" if suffix == "psd1" else r"%[sd]")
    wrong = [k for k in de if sorted(placeholder.findall(de[k])) != sorted(placeholder.findall(en[k]))]
    assert not wrong, f"Platzhalter in de/en.{suffix} stimmen nicht: {wrong}"


def _used_script_keys(pattern: str, globs: tuple[str, ...]) -> set[str]:
    used: set[str] = set()
    for glob in globs:
        for path in ROOT.glob(glob):
            used.update(re.findall(pattern, path.read_text(encoding="utf-8-sig")))
    return used


def test_powershell_scripts_only_use_existing_keys():
    known = set(_psd1_keys(SCRIPT_LOCALES / "de.psd1"))
    used = _used_script_keys(r"\bT\s+'([A-Za-z0-9_.]+)'", ("scripts/*.ps1", "scripts/lib/*.psm1"))
    assert used, "Keine T-Aufrufe gefunden"
    assert not used - known, f"Unbekannte Keys: {sorted(used - known)}"


def test_shell_scripts_only_use_existing_keys():
    known = set(_sh_keys(SCRIPT_LOCALES / "de.sh"))
    used = _used_script_keys(
        r"\bui_(?:t|step|ok|warn|fail|info|header|confirm)\s+([a-z][A-Za-z0-9_]*\.[A-Za-z0-9_.]+)",
        ("*.sh", "scripts/*.sh", "scripts/lib/*.sh"),
    )
    assert used, "Keine ui_*-Aufrufe gefunden"
    assert not used - known, f"Unbekannte Keys: {sorted(used - known)}"


def test_language_detection_prefers_env_then_file(tmp_path, monkeypatch):
    monkeypatch.delenv("LLMBENCH_LANG", raising=False)
    assert i18n.detect_language(tmp_path) == "de"
    assert not i18n.language_preselected(tmp_path)

    i18n.save_language("en", tmp_path)
    assert i18n.detect_language(tmp_path) == "en"
    assert i18n.language_preselected(tmp_path)

    monkeypatch.setenv("LLMBENCH_LANG", "de")
    assert i18n.detect_language(tmp_path) == "de"

    monkeypatch.setenv("LLMBENCH_LANG", "xx")
    assert i18n.detect_language(tmp_path) == "en"


def test_explicit_config_language_wins(tmp_path, monkeypatch):
    from llmbench.config import load_config

    monkeypatch.setenv("LLMBENCH_LANG", "en")
    cfg_path = tmp_path / "benchmark.yaml"
    cfg_path.write_text("project:\n  name: x\n", encoding="utf-8")
    try:
        assert load_config(cfg_path)["project"]["language"] == "en"
        assert i18n._("Fehler") == "Error"

        cfg_path.write_text("project:\n  language: de\n", encoding="utf-8")
        assert load_config(cfg_path)["project"]["language"] == "de"
        assert i18n._("Fehler") == "Fehler"
    finally:
        i18n.set_language("de")
