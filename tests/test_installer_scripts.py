"""Fuehrt die Installer-Skripte wirklich aus (PowerShell bzw. Bash).

Externe Programme (wsl, Windows-Features) werden durch PowerShell-Funktionen
ersetzt, sodass nichts installiert wird. Fehlt pwsh/bash, werden die Tests
uebersprungen; auf dem windows-latest-Runner der CI ist pwsh vorhanden.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
BASH = shutil.which("bash") if sys.platform != "win32" else None

needs_pwsh = pytest.mark.skipif(PWSH is None, reason="pwsh nicht installiert")
needs_bash = pytest.mark.skipif(BASH is None, reason="bash nicht verfuegbar")
# POSIX-Exitcodes sind 8 Bit breit: 3010 ("Neustart noetig") kommt dort als 194 an.
REBOOT_EXIT = 3010 if sys.platform == "win32" else 3010 % 256
# Attrappe fuer einen ausreichend neuen NVIDIA-Treiber.
DRIVER_OK = "function nvidia-smi { '590.44' }\n"


def _run(cmd: list[str], lang: str, extra_env: dict[str, str] | None = None):
    env = dict(os.environ)
    env.update({"LLMBENCH_LANG": lang, "NO_COLOR": "1"})
    env.update(extra_env or {})
    return subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


@needs_pwsh
def test_all_powershell_files_parse(tmp_path):
    script = tmp_path / "parse.ps1"
    script.write_text(
        "$bad = 0\n"
        "foreach ($f in (Get-ChildItem scripts -Recurse -Include *.ps1,*.psm1,*.psd1)) {\n"
        "  $e = $null\n"
        "  [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$null, [ref]$e) | Out-Null\n"
        "  foreach ($x in $e) { Write-Output \"$($f.Name): $x\"; $bad++ }\n"
        "}\n"
        "exit $bad\n",
        encoding="utf-8",
    )
    proc = _run([PWSH, "-NoProfile", "-File", str(script)], "de")
    assert proc.returncode == 0, proc.stdout + proc.stderr


@needs_pwsh
@pytest.mark.parametrize(
    ("lang", "expected"),
    [("de", "erst nach einem Neustart aktiv"), ("en", "only becomes active after a restart")],
)
def test_docker_setup_reports_reboot_in_chosen_language(tmp_path, lang, expected):
    # WSL fehlt scheinbar und bleibt nach "Installation" unregistriert -> Neustart noetig.
    script = tmp_path / "reboot.ps1"
    script.write_text(
        f"$env:ProgramFiles = '{tmp_path.as_posix()}'\n"
        f"{DRIVER_OK}"
        "function wsl { }\n"
        "function Get-WindowsOptionalFeature { throw 'n/a' }\n"
        f"& '{(ROOT / 'scripts' / 'DOCKER_BENCHMARK.ps1').as_posix()}' -Action Setup\n"
        "exit $LASTEXITCODE\n",
        encoding="utf-8",
    )
    proc = _run([PWSH, "-NoProfile", "-File", str(script)], lang, {"LLMBENCH_AUTO_INSTALL": "1"})
    assert proc.returncode == REBOOT_EXIT, proc.stdout + proc.stderr
    assert expected in proc.stdout


@needs_pwsh
def test_docker_setup_declined_install_fails_cleanly(tmp_path):
    script = tmp_path / "declined.ps1"
    script.write_text(
        f"$env:ProgramFiles = '{tmp_path.as_posix()}'\n"
        f"{DRIVER_OK}"
        "function wsl { }\n"
        "function Get-WindowsOptionalFeature { throw 'n/a' }\n"
        f"& '{(ROOT / 'scripts' / 'DOCKER_BENCHMARK.ps1').as_posix()}' -Action Setup\n"
        "exit $LASTEXITCODE\n",
        encoding="utf-8",
    )
    proc = _run([PWSH, "-NoProfile", "-File", str(script)], "en", {"LLMBENCH_AUTO_INSTALL": "0"})
    assert proc.returncode == 1
    assert "installation was declined" in proc.stdout
    # Kein PowerShell-Stacktrace mehr fuer den Nutzer.
    assert "CategoryInfo" not in proc.stdout + proc.stderr


@needs_pwsh
@pytest.mark.parametrize(
    ("stub", "expected"),
    [
        # Keine NVIDIA-Karte: gar nicht erst WSL/Docker installieren.
        ("function Get-CimInstance { @() }\n", "No NVIDIA graphics card found"),
        # Karte da, Treiber zu alt: Hinweis mit benoetigter Version.
        ("function nvidia-smi { '552.12' }\n", "552.12 is too old"),
    ],
)
def test_docker_setup_stops_early_without_suitable_nvidia_driver(tmp_path, stub, expected):
    script = tmp_path / "driver.ps1"
    script.write_text(
        f"$env:ProgramFiles = '{tmp_path.as_posix()}'\n"
        f"$env:SystemRoot = '{tmp_path.as_posix()}'\n"
        + stub
        + "function wsl { throw 'WSL darf nicht angefasst werden' }\n"
        f"& '{(ROOT / 'scripts' / 'DOCKER_BENCHMARK.ps1').as_posix()}' -Action Setup\n"
        "exit $LASTEXITCODE\n",
        encoding="utf-8",
    )
    proc = _run([PWSH, "-NoProfile", "-File", str(script)], "en", {"LLMBENCH_AUTO_INSTALL": "1"})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert expected in proc.stdout
    assert "Checking WSL" not in proc.stdout  # WSL-/Docker-Schritte wurden nie erreicht


@needs_pwsh
def test_resume_command_keeps_forced_mode(tmp_path):
    # Ein erzwungener Docker-Modus darf nach dem Neustart nicht auf "auto" zurueckfallen.
    script = tmp_path / "resume.ps1"
    script.write_text(
        f"Import-Module '{(ROOT / 'scripts' / 'lib' / 'UI.psm1').as_posix()}' -Force -DisableNameChecking\n"
        "Initialize-LlmbenchUI\n"
        "Get-ResumeCommand 'START_BENCHMARK.bat'\n",
        encoding="utf-8",
    )
    proc = _run([PWSH, "-NoProfile", "-File", str(script)], "en", {"LLMBENCH_EXECUTION_MODE": "docker"})
    assert proc.returncode == 0, proc.stderr
    command = proc.stdout.strip()
    assert command.startswith('cmd.exe /c "set "LLMBENCH_EXECUTION_MODE=docker" && ')
    assert 'set "LLMBENCH_LANG=en"' in command
    assert command.endswith('START_BENCHMARK.bat""')


@needs_bash
@pytest.mark.parametrize(("lang", "expected"), [("de", "Wie lange soll der Test laufen?"), ("en", "How long should")])
def test_bash_ui_menu_uses_chosen_language(tmp_path, lang, expected):
    script = tmp_path / "menu.sh"
    script.write_text(
        "set -euo pipefail\n"
        f"source '{(ROOT / 'scripts' / 'lib' / 'ui.sh').as_posix()}'\n"
        "ui_benchmark_options\n"
        'echo "RESULT=$UI_DURATION/$UI_HARDWARE/$UI_STRESS"\n'
        "LLMBENCH_AUTO_INSTALL=0 ui_confirm_install Docker || echo DECLINED\n",
        encoding="utf-8",
    )
    proc = _run([BASH, str(script)], lang)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert expected in proc.stdout
    # Ohne Terminal gelten die Standardwerte, und ohne Zustimmung wird nichts installiert.
    assert "RESULT=medium/both/0" in proc.stdout
    assert "DECLINED" in proc.stdout
    assert not re.search(r"<[a-z]+\.[a-z_.]+>", proc.stdout), "unbekannter Text-Schluessel"


@needs_bash
def test_bash_language_choice_is_saved(tmp_path):
    fake_root = tmp_path / "repo"
    shutil.copytree(ROOT / "scripts", fake_root / "scripts")
    script = tmp_path / "lang.sh"
    script.write_text(
        f"source '{(fake_root / 'scripts' / 'lib' / 'ui.sh').as_posix()}'\nui_select_language\necho \"LANG=$LLMBENCH_LANG\"\n",
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k != "LLMBENCH_LANG"}
    proc = subprocess.run(
        [BASH, str(script)], env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    assert "LANG=de" in proc.stdout
    assert (fake_root / ".runtime" / "language").read_text().strip() == "de"


def test_bootstrap_keeps_chosen_language(tmp_path, monkeypatch):
    """Frueher schrieb jeder bootstrap-Lauf (z. B. bei START_BENCHMARK) stumpf 'de' zurueck."""
    from llmbench.bootstrap import bootstrap_config

    monkeypatch.setenv("LLMBENCH_LANG", "en")
    cfg_path = tmp_path / "benchmark.yaml"
    bootstrap_config(cfg_path, tmp_path)
    assert yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["project"]["language"] == "en"

    # Ohne gewaehlte Sprache bleibt ein vorhandener Eintrag erhalten.
    monkeypatch.delenv("LLMBENCH_LANG")
    bootstrap_config(cfg_path, tmp_path)
    assert yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["project"]["language"] == "en"
