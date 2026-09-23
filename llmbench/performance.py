"""Volle Leistung waehrend eines Laufs: Energiesparmodi und Power-Limits aus.

Ein Benchmark soll messen, was die Hardware kann - nicht, was ein Energieplan
ihr gerade erlaubt. Vor dem Lauf stellt `PerformanceMode` deshalb alles auf
Hoechstleistung, was sich ohne Eingriff ins BIOS/UEFI umstellen laesst.
Standardmaessig bleibt das auch nach dem Lauf so (`performance.restore_after_run:
false`); `llmbench performance off` stellt exakt den vorherigen Zustand wieder her.

Linux
  * power-profiles-daemon bzw. tuned -> "performance"
  * ACPI-Plattformprofil -> "performance"
  * CPU-Governor -> "performance", Energy-Performance-Preference -> "performance"
  * Turbo/Boost an, `scaling_max_freq` auf das Hardware-Maximum
  * Intel-RAPL-Power-Limits auf das vom Hersteller erlaubte Maximum
  * PCIe-ASPM -> "performance"
  * NVIDIA: Persistence Mode an, Power-Limit auf `power.max_limit`
  * AMD: Power-Cap auf `power1_cap_max`, DPM-Level "high"

Windows
  * Eigener Energieplan (Kopie von "Ultimative Leistung", sonst
    "Hoechstleistung") mit 100 % Mindest-/Hoechst-Prozessorleistung,
    aggressivem Boost, ohne Core Parking, ohne PCIe-ASPM und ohne Standby
  * NVIDIA: Power-Limit auf `power.max_limit`

Alles, was geaendert wird, landet als Rueckbau-Plan mit den Originalwerten in
`.runtime/performance_state.json`. Jeder neue Start baut zuerst diesen Plan
zurueck und setzt dann neu - der gespeicherte "Originalzustand" ist also nie
einer, den llmbench selbst hinterlassen hat (auch nicht nach kill -9).

Ohne root/Administrator lassen sich nicht alle Punkte setzen. Das ist kein
Abbruchgrund: der Lauf geht weiter, jeder nicht gesetzte Punkt wird mit Grund
im Ergebnis festgehalten.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .i18n import _
from .utils import command_exists, utc_now_iso

STATE_FILE = Path(".runtime") / "performance_state.json"

WINDOWS_ULTIMATE_PERFORMANCE = "e9a42b02-d5df-448d-aa00-03f14749eb61"
WINDOWS_HIGH_PERFORMANCE = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
WINDOWS_SCHEME_NAME = "llmbench Volle Leistung"
GUID_RE = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")

# powercfg-Aliase (siehe `powercfg /aliases`), jeweils fuer Netz- und Akkubetrieb.
WINDOWS_SETTINGS: tuple[tuple[str, str, int], ...] = (
    ("SUB_PROCESSOR", "PROCTHROTTLEMIN", 100),
    ("SUB_PROCESSOR", "PROCTHROTTLEMAX", 100),
    ("SUB_PROCESSOR", "PERFBOOSTMODE", 2),  # 2 = Aggressiv
    ("SUB_PROCESSOR", "CPMINCORES", 100),  # kein Core Parking
    ("SUB_PCIEXPRESS", "ASPM", 0),
    ("SUB_SLEEP", "STANDBYIDLE", 0),
    ("SUB_DISK", "DISKIDLE", 0),
)

TUNED_PERFORMANCE_PROFILES = {
    "throughput-performance",
    "latency-performance",
    "accelerator-performance",
    "network-latency",
    "network-throughput",
}

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _default_runner(
    argv: list[str], input: str | None = None, timeout: float = 30.0, interactive: bool = False
) -> subprocess.CompletedProcess[str]:
    try:
        if interactive:
            # sudo -v muss das Passwort am Terminal abfragen koennen.
            proc = subprocess.run(argv, timeout=timeout, check=False)
            return subprocess.CompletedProcess(argv, proc.returncode, "", "")
        return subprocess.run(
            argv,
            input=input,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def _platform() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def _is_admin(platform_name: str) -> bool:
    if platform_name == "windows":
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except Exception:
            return False
    geteuid = getattr(os, "geteuid", None)
    return bool(geteuid and geteuid() == 0)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _bracketed(text: str | None) -> str | None:
    """`[default] performance powersave` -> `default` (sysfs-Auswahllisten)."""
    if not text:
        return None
    match = re.search(r"\[([^\]]+)\]", text)
    return match.group(1) if match else text.split()[0]


class PerformanceMode:
    """Kontextmanager: beim Eintritt volle Leistung, beim Verlassen Rueckbau."""

    def __init__(
        self,
        root: str | Path = ".",
        *,
        restore_on_exit: bool = True,
        use_sudo: bool = True,
        platform_name: str | None = None,
        sysfs_root: str | Path = "/",
        runner: Runner | None = None,
        is_admin: bool | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.state_file = Path(root) / STATE_FILE
        self.restore_on_exit = restore_on_exit
        self.use_sudo = use_sudo
        self.platform = platform_name or _platform()
        self.sys = Path(sysfs_root)
        self._runner = runner or _default_runner
        self.is_admin = _is_admin(self.platform) if is_admin is None else is_admin
        self._log = log or (lambda _msg: None)
        self.steps: list[dict[str, Any]] = []
        self.restore_plan: list[dict[str, Any]] = []
        self._sudo: bool | None = None
        self._old_sigterm: Any = None

    # ------------------------------------------------------------------ API

    @property
    def report(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "privileged": self.is_admin or bool(self._sudo),
            "applied_at": getattr(self, "_applied_at", None),
            "steps": list(self.steps),
            "restore_on_exit": self.restore_on_exit,
        }

    def failed_steps(self) -> list[dict[str, Any]]:
        return [s for s in self.steps if s["status"] == "failed"]

    def apply(self) -> dict[str, Any]:
        # Originalwerte eines frueheren Starts wiederherstellen, sonst wuerden
        # die bereits hochgesetzten Werte als "Original" gespeichert.
        restore_from_state(self.state_file.parent.parent, runner=self._runner, log=self._log)
        self._applied_at = utc_now_iso()
        if self.platform == "linux":
            self._apply_linux()
        elif self.platform == "windows":
            self._apply_windows()
        else:
            self._step("platform", "skipped", _("Auf dieser Plattform nicht unterstuetzt."))
        self._save_state()
        return self.report

    def restore(self) -> list[dict[str, Any]]:
        errors = _run_restore_plan(self.restore_plan, self._runner)
        self.restore_plan = []
        with contextlib.suppress(OSError):
            self.state_file.unlink()
        return errors

    def __enter__(self) -> PerformanceMode:
        self.apply()
        if self.restore_on_exit and threading.current_thread() is threading.main_thread():
            # SIGTERM (z. B. `docker stop`, systemd) beendet Python sonst ohne
            # __exit__ - die Hardware bliebe auf Volllast stehen.
            with contextlib.suppress(Exception):
                self._old_sigterm = signal.signal(signal.SIGTERM, _raise_system_exit)
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._old_sigterm is not None:
            with contextlib.suppress(Exception):
                signal.signal(signal.SIGTERM, self._old_sigterm)
        if not self.restore_on_exit:
            return
        errors = self.restore()
        if errors:
            self._log(
                _("Nicht alle Leistungseinstellungen konnten zurueckgesetzt werden: {errors}").format(
                    errors="; ".join(e["error"] for e in errors)
                )
            )
        elif self.steps:
            self._log(_("Leistungseinstellungen wurden auf den vorherigen Stand zurueckgesetzt."))

    # ------------------------------------------------------------- Helfer

    def _step(self, name: str, status: str, detail: str = "") -> None:
        self.steps.append({"name": name, "status": status, "detail": detail})

    def _run(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return self._runner(argv, **kwargs)

    def _save_state(self) -> None:
        if not self.restore_plan:
            with contextlib.suppress(OSError):
                self.state_file.unlink()
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps(
                    {"created_at": self._applied_at, "platform": self.platform, "restore": self.restore_plan},
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _sudo_available(self) -> bool:
        """`sudo -n` ohne Passwort, sonst einmalig interaktiv nachfragen."""
        if self._sudo is not None:
            return self._sudo
        self._sudo = False
        if self.is_admin or not self.use_sudo or self.platform != "linux" or not command_exists("sudo"):
            return False
        if self._run(["sudo", "-n", "true"], timeout=10).returncode == 0:
            self._sudo = True
            return True
        if sys.stdin is not None and sys.stdin.isatty():
            self._log(
                _("Fuer volle Leistung (Governor, Power-Limits) werden root-Rechte gebraucht. sudo fragt jetzt einmal nach dem Passwort.")
            )
            self._sudo = self._run(["sudo", "-v"], timeout=120, interactive=True).returncode == 0
        return self._sudo

    def _privileged(self, argv: list[str]) -> list[str]:
        if self.platform == "linux" and not self.is_admin and self._sudo_available():
            return ["sudo", "-n", *argv]
        return argv

    def _write(self, path: Path, value: str) -> str | None:
        """Schreibt einen sysfs-Wert. Liefert None bei Erfolg, sonst den Fehler."""
        try:
            path.write_text(value, encoding="utf-8")
            return None
        except PermissionError as exc:
            if not self._sudo_available():
                return f"{exc.strerror or exc}"
        except OSError as exc:
            return f"{exc.strerror or exc}"
        cp = self._run(["sudo", "-n", "tee", str(path)], input=value, timeout=10)
        if cp.returncode == 0:
            return None
        return (cp.stderr or cp.stdout or f"sudo tee exit {cp.returncode}").strip()

    def _set_files(self, name: str, changes: list[tuple[Path, str]]) -> None:
        """Mehrere sysfs-Dateien gleicher Art setzen und als ein Schritt melden."""
        if not changes:
            return
        applied, already, errors = 0, 0, []
        for path, target in changes:
            current = _read(path)
            if current is None:
                continue
            if current == target:
                already += 1
                continue
            error = self._write(path, target)
            if error:
                errors.append(error)
                continue
            applied += 1
            self.restore_plan.append({"kind": "write", "path": str(path), "value": current})
        if errors:
            self._step(name, "failed", f"{applied}/{applied + len(errors)} gesetzt: {errors[0]}")
        elif applied:
            self._step(name, "applied", f"{applied} gesetzt")
        elif already:
            self._step(name, "already", "")

    def _choice_file(self, name: str, path: Path, choices_path: Path | None, target: str) -> None:
        if not path.exists():
            return
        if choices_path is not None:
            choices = (_read(choices_path) or "").replace("[", " ").replace("]", " ").split()
            if target not in choices:
                self._step(name, "skipped", f"'{target}' nicht verfuegbar")
                return
        current = _read(path)
        if current is None:
            return
        selected = _bracketed(current) if "[" in current else current
        if selected == target:
            self._step(name, "already", "")
            return
        error = self._write(path, target)
        if error:
            self._step(name, "failed", error)
            return
        self.restore_plan.append({"kind": "write", "path": str(path), "value": selected})
        self._step(name, "applied", f"{selected} -> {target}")

    # --------------------------------------------------------------- Linux

    def _apply_linux(self) -> None:
        self._linux_power_profile()
        cpu = self.sys / "sys" / "devices" / "system" / "cpu"
        acpi = self.sys / "sys" / "firmware" / "acpi"
        self._choice_file(
            "ACPI platform_profile", acpi / "platform_profile", acpi / "platform_profile_choices", "performance"
        )

        policies = sorted(cpu.glob("cpufreq/policy*")) or sorted(cpu.glob("cpu[0-9]*/cpufreq"))
        governors = []
        for pol in policies:
            available = (_read(pol / "scaling_available_governors") or "").split()
            if "performance" in available:
                governors.append((pol / "scaling_governor", "performance"))
        self._set_files(_("CPU-Governor"), governors)

        epp = []
        for pol in policies:
            available = (_read(pol / "energy_performance_available_preferences") or "").split()
            if "performance" in available:
                epp.append((pol / "energy_performance_preference", "performance"))
        self._set_files("CPU energy_performance_preference", epp)

        max_freq = []
        for pol in policies:
            hw_max = _read(pol / "cpuinfo_max_freq")
            if hw_max and (pol / "scaling_max_freq").exists():
                max_freq.append((pol / "scaling_max_freq", hw_max))
        self._set_files("CPU scaling_max_freq", max_freq)

        turbo: list[tuple[Path, str]] = []
        pstate = cpu / "intel_pstate"
        if (pstate / "no_turbo").exists():
            turbo.append((pstate / "no_turbo", "0"))
        if (pstate / "max_perf_pct").exists():
            turbo.append((pstate / "max_perf_pct", "100"))
        if (cpu / "cpufreq" / "boost").exists():
            turbo.append((cpu / "cpufreq" / "boost", "1"))
        turbo.extend((pol / "boost", "1") for pol in policies if (pol / "boost").exists())
        self._set_files(_("CPU-Turbo/Boost"), turbo)

        self._linux_rapl()
        self._choice_file(
            "PCIe ASPM",
            self.sys / "sys" / "module" / "pcie_aspm" / "parameters" / "policy",
            self.sys / "sys" / "module" / "pcie_aspm" / "parameters" / "policy",
            "performance",
        )
        self._nvidia()
        self._linux_amd_gpu()

    def _linux_power_profile(self) -> None:
        if command_exists("powerprofilesctl"):
            cp = self._run(["powerprofilesctl", "get"], timeout=10)
            current = cp.stdout.strip() if cp.returncode == 0 else ""
            if not current:
                self._step("power-profiles-daemon", "failed", (cp.stderr or "").strip())
                return
            if current == "performance":
                self._step("power-profiles-daemon", "already", "")
                return
            cp = self._run(["powerprofilesctl", "set", "performance"], timeout=10)
            if cp.returncode != 0:
                cp = self._run(self._privileged(["powerprofilesctl", "set", "performance"]), timeout=10)
            if cp.returncode == 0:
                self.restore_plan.append({"kind": "cmd", "argv": ["powerprofilesctl", "set", current]})
                self._step("power-profiles-daemon", "applied", f"{current} -> performance")
            else:
                self._step("power-profiles-daemon", "failed", (cp.stderr or cp.stdout).strip())
            return
        if command_exists("tuned-adm"):
            cp = self._run(["tuned-adm", "active"], timeout=10)
            match = re.search(r":\s*(\S+)", cp.stdout or "")
            current = match.group(1) if match else ""
            if current in TUNED_PERFORMANCE_PROFILES:
                self._step("tuned", "already", current)
                return
            cp = self._run(self._privileged(["tuned-adm", "profile", "throughput-performance"]), timeout=60)
            if cp.returncode == 0:
                restore = ["tuned-adm", "profile", current] if current else ["tuned-adm", "off"]
                self.restore_plan.append({"kind": "cmd", "argv": restore, "privileged": True})
                self._step("tuned", "applied", f"{current or 'off'} -> throughput-performance")
            else:
                self._step("tuned", "failed", (cp.stderr or cp.stdout).strip())

    def _linux_rapl(self) -> None:
        powercap = self.sys / "sys" / "class" / "powercap"
        changes = []
        # "intel-rapl:0", "intel-rapl:0:1", "intel-rapl-mmio:0"; der Steuerordner
        # "intel-rapl" selbst hat keine constraint_*-Dateien.
        for zone in sorted(powercap.glob("intel-rapl*")):
            for limit in sorted(zone.glob("constraint_*_power_limit_uw")):
                prefix = limit.name[: -len("power_limit_uw")]
                hw_max = _to_int(_read(zone / f"{prefix}max_power_uw"))
                current = _to_int(_read(limit))
                if hw_max and current is not None and hw_max > current:
                    changes.append((limit, str(hw_max)))
        self._set_files(_("CPU-Power-Limit (RAPL)"), changes)

    def _linux_amd_gpu(self) -> None:
        caps, levels = [], []
        for dev in sorted((self.sys / "sys" / "class" / "drm").glob("card[0-9]*/device")):
            if (_read(dev / "vendor") or "").lower() != "0x1002":
                continue
            for hwmon in sorted(dev.glob("hwmon/hwmon*")):
                cap_max = _to_int(_read(hwmon / "power1_cap_max"))
                cap = _to_int(_read(hwmon / "power1_cap"))
                if cap_max and cap is not None and cap_max > cap:
                    caps.append((hwmon / "power1_cap", str(cap_max)))
            if (dev / "power_dpm_force_performance_level").exists():
                levels.append((dev / "power_dpm_force_performance_level", "high"))
        self._set_files(_("AMD-GPU-Power-Limit"), caps)
        self._set_files("AMD GPU DPM-Level", levels)

    # ------------------------------------------------------------- NVIDIA

    def _nvidia(self) -> None:
        if not command_exists("nvidia-smi"):
            return
        fields = "index,persistence_mode,power.limit,power.max_limit"
        cp = self._run(["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"], timeout=20)
        if cp.returncode != 0:
            self._step(_("NVIDIA-Power-Limit"), "failed", (cp.stderr or cp.stdout).strip())
            return
        for line in cp.stdout.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue
            idx, persistence, limit, max_limit = parts[:4]
            label = f"GPU {idx}"
            if self.platform == "linux" and persistence.lower() == "disabled":
                self._nvidia_cmd(
                    f"NVIDIA Persistence Mode ({label})",
                    ["nvidia-smi", "-i", idx, "-pm", "1"],
                    ["nvidia-smi", "-i", idx, "-pm", "0"],
                    "Disabled -> Enabled",
                )
            current, maximum = _to_float(limit), _to_float(max_limit)
            name = _("NVIDIA-Power-Limit") + f" ({label})"
            if current is None or maximum is None:
                self._step(name, "skipped", "Power-Limit nicht einstellbar")
            elif current >= maximum - 0.5:
                self._step(name, "already", f"{current:g} W")
            else:
                self._nvidia_cmd(
                    name,
                    ["nvidia-smi", "-i", idx, "-pl", f"{maximum:g}"],
                    ["nvidia-smi", "-i", idx, "-pl", f"{current:g}"],
                    f"{current:g} W -> {maximum:g} W",
                )

    def _nvidia_cmd(self, name: str, argv: list[str], restore: list[str], detail: str) -> None:
        if self.platform == "windows" and not self.is_admin:
            self._step(name, "skipped", _("Administratorrechte fehlen."))
            return
        if self.platform == "linux" and not self.is_admin and not self._sudo_available():
            self._step(name, "skipped", _("root-Rechte fehlen."))
            return
        cp = self._run(self._privileged(argv), timeout=30)
        if cp.returncode == 0:
            self.restore_plan.append({"kind": "cmd", "argv": restore, "privileged": True})
            self._step(name, "applied", detail)
        else:
            self._step(name, "failed", (cp.stderr or cp.stdout).strip())

    # ------------------------------------------------------------ Windows

    def _apply_windows(self) -> None:
        self._windows_scheme()
        self._nvidia()

    def _windows_scheme(self) -> None:
        name = _("Energieplan")
        cp = self._run(["powercfg", "/getactivescheme"], timeout=15)
        match = GUID_RE.search(cp.stdout or "")
        if cp.returncode != 0 or not match:
            self._step(name, "failed", (cp.stderr or cp.stdout or "powercfg").strip())
            return
        original = match.group(0).lower()

        scheme = None
        for base in (WINDOWS_ULTIMATE_PERFORMANCE, WINDOWS_HIGH_PERFORMANCE, "SCHEME_CURRENT"):
            dup = self._run(["powercfg", "/duplicatescheme", base], timeout=15)
            found = GUID_RE.search(dup.stdout or "") if dup.returncode == 0 else None
            if found:
                scheme = found.group(0).lower()
                break
        if not scheme:
            self._step(name, "failed", _("Kein Hoechstleistungs-Energieplan verfuegbar."))
            return
        # Rueckbau laeuft rueckwaerts: erst den alten Plan aktivieren, dann die Kopie loeschen.
        self.restore_plan.append({"kind": "cmd", "argv": ["powercfg", "/delete", scheme]})
        self._run(["powercfg", "/changename", scheme, WINDOWS_SCHEME_NAME], timeout=15)

        failed = []
        for sub, setting, value in WINDOWS_SETTINGS:
            for verb in ("/setacvalueindex", "/setdcvalueindex"):
                res = self._run(["powercfg", verb, scheme, sub, setting, str(value)], timeout=15)
                if res.returncode != 0 and setting not in failed:
                    failed.append(setting)

        act = self._run(["powercfg", "/setactive", scheme], timeout=15)
        if act.returncode != 0:
            self._step(name, "failed", (act.stderr or act.stdout).strip())
            return
        self.restore_plan.append({"kind": "cmd", "argv": ["powercfg", "/setactive", original]})
        detail = f"{original} -> {WINDOWS_SCHEME_NAME} ({scheme})"
        if failed:
            detail += "; nicht gesetzt: " + ", ".join(failed)
        self._step(name, "applied", detail)


def _raise_system_exit(signum: int, _frame: Any) -> None:
    raise SystemExit(128 + signum)


def _run_restore_plan(plan: list[dict[str, Any]], runner: Runner) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    is_root = _is_admin(_platform())
    for action in reversed(plan):
        try:
            if action["kind"] == "write":
                path = Path(action["path"])
                try:
                    path.write_text(action["value"], encoding="utf-8")
                except PermissionError:
                    cp = runner(["sudo", "-n", "tee", str(path)], input=action["value"], timeout=10)
                    if cp.returncode != 0:
                        raise OSError((cp.stderr or "sudo tee").strip()) from None
            elif action["kind"] == "cmd":
                argv = list(action["argv"])
                if action.get("privileged") and os.name != "nt" and not is_root and command_exists("sudo"):
                    argv = ["sudo", "-n", *argv]
                cp = runner(argv, timeout=60)
                if cp.returncode != 0:
                    raise OSError((cp.stderr or cp.stdout or f"exit {cp.returncode}").strip())
        except Exception as exc:
            errors.append({"action": action, "error": str(exc)})
    return errors


def restore_from_state(
    root: str | Path = ".", runner: Runner | None = None, log: Callable[[str], None] | None = None
) -> bool:
    """Stellt einen von einem abgebrochenen Lauf hinterlassenen Zustand wieder her."""
    state_file = Path(root) / STATE_FILE
    if not state_file.is_file():
        return False
    try:
        plan = json.loads(state_file.read_text(encoding="utf-8")).get("restore") or []
    except (OSError, ValueError):
        plan = []
    errors = _run_restore_plan(plan, runner or _default_runner)
    if errors and log:
        log("; ".join(e["error"] for e in errors))
    with contextlib.suppress(OSError):
        state_file.unlink()
    return True


def format_steps(steps: list[dict[str, Any]]) -> list[str]:
    marks = {"applied": "OK", "already": "OK", "skipped": "--", "failed": "!!"}
    lines = []
    for step in steps:
        detail = step.get("detail") or (_("bereits aktiv") if step["status"] == "already" else "")
        lines.append(f"[{marks.get(step['status'], '??')}] {step['name']}" + (f": {detail}" if detail else ""))
    return lines
