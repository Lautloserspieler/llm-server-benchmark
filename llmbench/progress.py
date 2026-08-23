"""Fortschrittsanzeige waehrend eines Benchmarklaufs.

Die Statuszeile wird mit einem Wagenruecklauf ueberschrieben statt mit
ANSI-Steuerzeichen. Das funktioniert auch in der klassischen Windows-Konsole,
in der die Terminalsteuerung nicht immer aktiv ist.

Ohne Terminal (Umleitung in eine Datei, Aufruf aus einem anderen Programm)
schaltet die Anzeige selbsttaetig auf einzelne Zeilen um, damit im Log nicht
tausende Fortschrittszeilen landen.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from typing import Any, TextIO


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _human_gib(value: float | int | None) -> str:
    if not value:
        return "—"
    return f"{float(value) / (1024 ** 3):.1f}"


def telemetry_line(sample: dict[str, Any] | None) -> str:
    """Kurzfassung eines Telemetrie-Samples fuer die Statuszeile."""
    if not sample:
        return ""
    parts: list[str] = []
    cpu = sample.get("cpu_percent")
    if cpu is not None:
        parts.append(f"CPU {float(cpu):.0f}%")
    gpus = sample.get("gpus") or []
    if gpus:
        gpu = gpus[0]
        util = gpu.get("util_gpu_percent")
        if util is not None:
            parts.append(f"GPU {float(util):.0f}%")
        used = gpu.get("memory_used_bytes")
        total = gpu.get("memory_total_bytes")
        if used and total:
            parts.append(f"{_human_gib(used)}/{_human_gib(total)} GiB")
        power = gpu.get("power_w")
        if power:
            parts.append(f"{float(power):.0f} W")
        temp = gpu.get("temperature_c")
        if temp:
            parts.append(f"{float(temp):.0f} °C")
    elif sample.get("ram_percent") is not None:
        parts.append(f"RAM {float(sample['ram_percent']):.0f}%")
    return " · ".join(parts)


class Reporter:
    """Gemeinsame Basis. Ohne Terminal wird nur zeilenweise berichtet."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdout
        self.total_tests = 0
        self.finished_tests = 0
        self._durations: dict[str, list[float]] = {}
        self._current_started: float | None = None
        self._current_label = ""
        self._current_kind = ""

    # ------------------------------------------------------------- Lebenslauf

    def run_started(self, server_name: str, total_tests: int) -> None:
        self.total_tests = total_tests
        self._write_line(f"Benchmark auf {server_name}: {total_tests} Einzeltests")

    def test_started(self, model: str, profile: str, kind: str) -> None:
        self._current_started = time.perf_counter()
        self._current_kind = kind
        self._current_label = f"{model} · {profile} · {kind}"
        self._write_line(f"[{self.finished_tests + 1}/{self.total_tests}] {self._current_label}")

    def progress(self, note: str = "", sample: dict[str, Any] | None = None) -> None:
        """Zwischenstand. Wird ohne Terminal bewusst verworfen."""

    def test_finished(self, status: str, rows: list[dict[str, Any]], error: str | None = None) -> None:
        elapsed = time.perf_counter() - (self._current_started or time.perf_counter())
        self._durations.setdefault(self._current_kind, []).append(elapsed)
        self.finished_tests += 1
        self._clear()
        if status == "ok":
            for row in rows:
                self._write_line(
                    f"    {row.get('test', '?'):<22} {float(row.get('avg_ts') or 0):>10.2f} t/s"
                    f"   ±{float(row.get('stddev_ts') or 0):.2f}"
                )
        else:
            label = "Zeitueberschreitung" if status == "timeout" else "Fehler"
            self._write_line(f"    {label}: {error or 'unbekannt'}")

    def note(self, text: str) -> None:
        self._clear()
        self._write_line(f"    {text}")

    def run_finished(self) -> None:
        self._clear()

    # -------------------------------------------------------------- Restzeit

    def remaining_seconds(self) -> float | None:
        """Hochrechnung anhand der bisher gemessenen Dauern.

        Gemittelt wird je Testart: ein Long-Context-Test dauert um ein
        Vielfaches laenger als ein Prompt-Test, ein Gesamtmittel waere
        deshalb deutlich daneben.
        """
        if not self._durations or self.finished_tests >= self.total_tests:
            return None
        all_durations = [d for values in self._durations.values() for d in values]
        overall = sum(all_durations) / len(all_durations)
        if overall < 1.0:
            # Zu duenne Datenbasis. Eine Schaetzung von "00:00" waere
            # irrefuehrender als gar keine.
            return None
        per_kind = {k: sum(v) / len(v) for k, v in self._durations.items()}
        average = per_kind.get(self._current_kind, overall)

        # Der laufende Test zaehlt separat: von ihm ist nur noch der Rest offen.
        # Laeuft er bereits laenger als der Durchschnitt, wird er nicht negativ
        # gerechnet, sondern mit null Restdauer angesetzt.
        open_after_current = max(0, self.total_tests - self.finished_tests - 1)
        estimate = open_after_current * average
        if self._current_started is not None:
            running = time.perf_counter() - self._current_started
            estimate += max(0.0, average - running)
        else:
            estimate += average
        return estimate

    # ---------------------------------------------------------------- Ausgabe

    def _write_line(self, text: str) -> None:
        self.stream.write(text + "\n")
        self.stream.flush()

    def _clear(self) -> None:
        pass


class LiveReporter(Reporter):
    """Statuszeile, die sich fortlaufend selbst ueberschreibt."""

    MIN_INTERVAL = 0.2

    def __init__(self, stream: TextIO | None = None) -> None:
        super().__init__(stream)
        self._last_draw = 0.0
        self._line_length = 0
        self._note = ""

    def _width(self) -> int:
        try:
            return max(40, shutil.get_terminal_size(fallback=(100, 25)).columns - 1)
        except Exception:
            return 100

    def _clear(self) -> None:
        if self._line_length:
            self.stream.write("\r" + " " * self._line_length + "\r")
            self.stream.flush()
            self._line_length = 0

    def _draw(self, text: str) -> None:
        width = self._width()
        if len(text) > width:
            text = text[: width - 1] + "…"
        padding = max(0, self._line_length - len(text))
        self.stream.write("\r" + text + " " * padding)
        self.stream.flush()
        self._line_length = len(text)

    def test_started(self, model: str, profile: str, kind: str) -> None:
        self._note = ""
        super().test_started(model, profile, kind)
        self.progress()

    def progress(self, note: str = "", sample: dict[str, Any] | None = None) -> None:
        if note:
            self._note = note
        now = time.perf_counter()
        if now - self._last_draw < self.MIN_INTERVAL:
            return
        self._last_draw = now

        elapsed = now - (self._current_started or now)
        parts = [f"  laeuft {format_duration(elapsed)}"]
        if self._note:
            parts.append(self._note)
        telemetry = telemetry_line(sample)
        if telemetry:
            parts.append(telemetry)
        remaining = self.remaining_seconds()
        if remaining is not None:
            parts.append(f"noch ca. {format_duration(remaining)}")
        self._draw(" · ".join(parts))

    def run_finished(self) -> None:
        self._clear()


def make_reporter(force_plain: bool = False, stream: TextIO | None = None) -> Reporter:
    """Waehlt die passende Anzeige.

    Eine sich selbst ueberschreibende Zeile ergibt nur an einem echten
    Terminal Sinn. Bei Umleitung in eine Datei entstuenden daraus tausende
    unbrauchbare Zeilen.
    """
    stream = stream or sys.stdout
    if force_plain or os.environ.get("LLMBENCH_PLAIN_OUTPUT"):
        return Reporter(stream)
    try:
        interactive = stream.isatty()
    except Exception:
        interactive = False
    return LiveReporter(stream) if interactive else Reporter(stream)
