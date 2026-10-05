from __future__ import annotations

import contextlib
import json
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

from .config import normalize_flash_attention
from .i18n import _
from .llama_flags import load_flags, no_op_offload_flags
from .monitor import ResourceMonitor, strip_samples
from .utils import csv_value, file_fingerprint, kill_process_tree, read_json, resolve_executable, run_capture, utc_now_iso, write_json


def _extract_json(stdout: str) -> list[dict[str, Any]]:
    text = stdout.strip()
    if not text:
        raise ValueError("llama-bench hat nichts auf stdout ausgegeben")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end < start:
            raise
        data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("Die JSON-Ausgabe von llama-bench ist keine Liste")
    return data


def _extract_partial_json_rows(stdout: str) -> list[dict[str, Any]]:
    """Rettet vollstaendige llama-bench-Zeilen aus einem abgebrochenen JSON-Array.

    llama-bench schreibt erfolgreiche Teiltests bereits nach stdout. Scheitert
    erst eine spaetere Long-Context-Stufe, fehlt dem JSON-Array nur noch sein
    Abschluss. Ein Decoder pro Objekt kann die bis dahin vollstaendigen Zeilen
    trotzdem sicher lesen.
    """
    text = stdout.strip()
    start = text.find("[")
    if start < 0:
        return []

    decoder = json.JSONDecoder()
    rows: list[dict[str, Any]] = []
    index = start + 1
    while index < len(text):
        while index < len(text) and (text[index].isspace() or text[index] == ","):
            index += 1
        if index >= len(text) or text[index] == "]":
            break
        try:
            value, index = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            break
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _long_context_failure_metadata(
    rows: list[dict[str, Any]],
    bench_cfg: dict[str, Any],
    stderr: str,
    *,
    timed_out: bool = False,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    parts_by_depth: dict[int, set[str]] = {}
    for row in rows:
        depth = int(row.get("n_depth") or 0)
        parts = parts_by_depth.setdefault(depth, set())
        if int(row.get("n_prompt") or 0) > 0:
            parts.add("prompt")
        if int(row.get("n_gen") or 0) > 0:
            parts.add("generation")
    completed = sorted(
        depth
        for depth, parts in parts_by_depth.items()
        if {"prompt", "generation"}.issubset(parts)
    )
    requested = [int(value) for value in bench_cfg.get("context_depths", [])]
    missing = [depth for depth in requested if depth not in completed]
    failed_depth = missing[0] if missing else None

    text = (stderr or "").lower()
    capacity_markers = (
        "failed to create context",
        "out of memory",
        "cuda out of memory",
        "failed to allocate",
        "allocation failed",
        "insufficient memory",
        "not enough memory",
    )
    capacity_limited = any(marker in text for marker in capacity_markers)

    max_completed = max(completed) if completed else None
    if timed_out:
        timeout_text = f" nach {timeout_s:.0f} s" if timeout_s is not None else ""
        if failed_depth is not None:
            message = (
                "Long-Context-Test teilweise erfolgreich: Messwerte bis "
                f"{max_completed if max_completed is not None else '?'} Tokens wurden gespeichert; "
                f"Kontextstufe {failed_depth} war beim Zeitlimit{timeout_text} noch nicht fertig."
            )
        else:
            message = (
                "Long-Context-Test teilweise erfolgreich: Bereits abgeschlossene Messwerte "
                f"wurden gespeichert, bevor das Zeitlimit{timeout_text} erreicht wurde."
            )
        limit_status = "timeout"
        capacity_limited = False
    else:
        if failed_depth is not None:
            message = (
                "Long-Context-Test teilweise erfolgreich: Messwerte bis "
                f"{max_completed if max_completed is not None else '?'} Tokens wurden gespeichert; "
                f"Kontextstufe {failed_depth} konnte nicht erstellt werden."
            )
        else:
            message = (
                "Long-Context-Test teilweise erfolgreich: Bereits abgeschlossene Messwerte "
                "wurden gespeichert, bevor llama-bench abgebrochen ist."
            )
        if capacity_limited:
            message += " Die fehlende Stufe wird als Kapazitaetsgrenze behandelt."
        limit_status = "skipped_capacity" if capacity_limited else "failed"

    return {
        "completed_context_depths": completed,
        "failed_context_depth": failed_depth,
        "limit_status": limit_status,
        "capacity_limited": capacity_limited,
        "message": message,
    }


def probe_build(exe: str, with_hash: bool = True) -> dict[str, Any]:
    """Identitaet des verwendeten llama.cpp-Builds festhalten.

    Ohne diese Angabe laesst sich spaeter nicht belegen, dass zwei Server
    mit demselben Build gemessen haben.
    """
    info: dict[str, Any] = {}
    try:
        resolved = resolve_executable(exe)
    except FileNotFoundError as exc:
        return {"error": str(exc)}

    info["binary"] = file_fingerprint(resolved, with_hash=with_hash)
    try:
        cp = run_capture([resolved, "--list-devices"], timeout=30)
        text = ((cp.stdout or "") + (cp.stderr or "")).strip()
        info["devices_output"] = text[:600]
        info["devices_probe_returncode"] = cp.returncode
    except Exception as exc:
        info["devices_output"] = f"nicht ermittelbar: {exc}"

    marker = Path(resolved).parent / ".llama-build.json"
    if marker.exists():
        try:
            info["build_marker"] = read_json(marker)
        except Exception as exc:
            info["build_marker"] = {"error": str(exc)}
    return info


def _drain(stream: IO[str], sink: list[str], on_line: Callable[[str], None] | None) -> None:
    """Liest einen Ausgabestrom mit und meldet jede fertige Zeile.

    llama-bench trennt seine Fortschrittsmeldungen mit Wagenruecklauf statt
    Zeilenumbruch, damit sie sich im Terminal ueberschreiben. readline() wuerde
    darauf warten, dass irgendwann ein \n kommt - deshalb wird hier zeichenweise
    gelesen und bei beiden Trennzeichen abgeschlossen.
    """
    buffer: list[str] = []
    try:
        while True:
            char = stream.read(1)
            if not char:
                break
            if char in ("\r", "\n"):
                if buffer:
                    line = "".join(buffer)
                    sink.append(line)
                    if on_line:
                        with contextlib.suppress(Exception):
                            on_line(line)
                    buffer = []
                continue
            buffer.append(char)
    except Exception:
        pass
    finally:
        if buffer:
            line = "".join(buffer)
            sink.append(line)
            if on_line:
                with contextlib.suppress(Exception):
                    on_line(line)


def _base_args(
    exe: str,
    model_path: str,
    bench_cfg: dict[str, Any],
    profile: dict[str, Any],
    with_progress: bool = True,
    with_no_mmap: bool = True,
) -> list[str]:
    args = [
        exe,
        "-m", model_path,
        "-r", str(bench_cfg["repetitions"]),
        "--delay", str(bench_cfg.get("delay_seconds", 0)),
        "-o", "json",
        "-b", str(bench_cfg["batch_size"]),
        "-ub", str(bench_cfg["ubatch_size"]),
        "-fa", normalize_flash_attention(bench_cfg.get("flash_attention", "auto")),
        "-ctk", str(bench_cfg.get("cache_type_k", "f16")),
        "-ctv", str(bench_cfg.get("cache_type_v", "f16")),
        "-ngl", str(profile.get("gpu_layers", -1)),
    ]
    is_cpu_only = str(profile.get("gpu_layers", -1)) == "0"
    args += load_flags(
        exe,
        no_mmap=with_no_mmap and (bool(profile.get("no_mmap")) or is_cpu_only),
        mlock=bool(profile.get("mlock")),
    )
    if is_cpu_only:
        # -ngl 0 allein reicht bei CUDA-Builds nicht zwingend: Host-Tensor-
        # Operationen koennen weiterhin auf die GPU ausgelagert werden.
        args.extend(["-dev", "none"])
        args += no_op_offload_flags(exe, benchmark=True)
    if with_progress:
        args.append("--progress")
    threads = profile.get("threads", "auto")
    if threads not in (None, "auto", -1):
        args.extend(["-t", str(threads)])
    if profile.get("cpu_moe_layers") is not None:
        args.extend(["-ncmoe", str(profile["cpu_moe_layers"])])
    if profile.get("no_kv_offload"):
        args.extend(["-nkvo", "1"])
    if profile.get("device") and not is_cpu_only:
        args.extend(["-dev", str(profile["device"])])
    if profile.get("tensor_split"):
        args.extend(["-ts", str(profile["tensor_split"])])
    for item in profile.get("additional_args", []) or []:
        args.append(str(item))
    return args


_REJECTED_WORDS = ("invalid parameter", "invalid argument", "unknown argument")


def _rejected_flag(flag: str, stdout: str, stderr: str) -> bool:
    text = (stdout or "") + (stderr or "")
    return flag in text and any(word in text for word in _REJECTED_WORDS)


def _rejected_progress(stdout: str, stderr: str) -> bool:
    return _rejected_flag("--progress", stdout, stderr)


def _rejected_no_mmap(stdout: str, stderr: str) -> bool:
    return _rejected_flag("--no-mmap", stdout, stderr)


def _execute(
    args: list[str],
    timeout_s: float,
    monitor: ResourceMonitor,
    on_progress: Callable[[str, dict[str, Any] | None], None] | None,
) -> tuple[str, str, int | None, bool]:
    timed_out = False
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    monitor.set_target_pid(proc.pid)

    out_lines: list[str] = []
    err_lines: list[str] = []

    def _report(line: str) -> None:
        if on_progress:
            on_progress(line.strip(), monitor.latest())

    out_thread = threading.Thread(target=_drain, args=(proc.stdout, out_lines, None), daemon=True)
    err_thread = threading.Thread(target=_drain, args=(proc.stderr, err_lines, _report), daemon=True)
    out_thread.start()
    err_thread.start()

    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_process_tree(proc)
        with contextlib.suppress(Exception):
            proc.wait(timeout=30)

    out_thread.join(timeout=10)
    err_thread.join(timeout=10)

    return "\n".join(out_lines), "\n".join(err_lines), proc.returncode, timed_out


def _test_args(base: list[str], bench_cfg: dict[str, Any], test_kind: str) -> list[str]:
    args = list(base)
    if test_kind == "prompt":
        args.extend(["-p", csv_value(bench_cfg["prompt_tokens"]), "-n", "0", "-d", "0"])
    elif test_kind == "generation":
        args.extend(["-p", "0", "-n", csv_value(bench_cfg["generation_tokens"]), "-d", "0"])
    elif test_kind == "long_context":
        args.extend([
            "-p", str(bench_cfg["long_context_prompt_tokens"]),
            "-n", str(bench_cfg["long_context_generation_tokens"]),
            "-d", csv_value(bench_cfg["context_depths"]),
        ])
    else:
        raise ValueError(f"Unbekannte Testart: {test_kind}")
    return args


def _benchmark_timeout_seconds(
    bench_cfg: dict[str, Any],
    profile: dict[str, Any],
) -> float:
    """Resolve a benchmark timeout without changing measurement semantics.

    CPU-only inference on large models can be orders of magnitude slower than
    GPU inference. A single global timeout caused valid long CPU runs to be
    aborted while the machine was still making progress.
    """
    profile_timeout = profile.get("timeout_seconds")
    if profile_timeout not in (None, ""):
        return float(profile_timeout)

    try:
        is_cpu = int(profile.get("gpu_layers", -1)) == 0
    except (TypeError, ValueError):
        is_cpu = False

    key = "cpu_timeout_seconds" if is_cpu else "gpu_timeout_seconds"
    return float(bench_cfg.get(key, bench_cfg.get("timeout_seconds", 3600)))


def _timeout_message(
    test_kind: str,
    profile: dict[str, Any],
    timeout_s: float,
) -> str:
    try:
        is_cpu = int(profile.get("gpu_layers", -1)) == 0
    except (TypeError, ValueError):
        is_cpu = False

    if is_cpu:
        return (
            f"llama-bench wurde nach {timeout_s:.0f} s abgebrochen. "
            "Der CPU-Lauf war noch nicht fertig; grosse Modelle, viele Wiederholungen "
            "oder lange Generationen koennen deutlich laenger dauern. "
            "benchmark.cpu_timeout_seconds erhoehen oder den Lauf kuerzen."
        )
    if test_kind == "long_context":
        return (
            f"llama-bench wurde nach {timeout_s:.0f} s abgebrochen. "
            "Der Long-Context-Lauf hat das Zeitlimit erreicht; Kontexttiefe reduzieren "
            "oder benchmark.gpu_timeout_seconds erhoehen."
        )
    return (
        f"llama-bench wurde nach {timeout_s:.0f} s abgebrochen. "
        "benchmark.gpu_timeout_seconds erhoehen, falls der Lauf absichtlich so lange dauert."
    )


def run_llama_bench(
    exe: str,
    model_path: str,
    bench_cfg: dict[str, Any],
    profile: dict[str, Any],
    test_kind: str,
    output_dir: Path,
    on_progress: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    exe = resolve_executable(exe)
    args = _test_args(_base_args(exe, model_path, bench_cfg, profile), bench_cfg, test_kind)

    timeout_s = _benchmark_timeout_seconds(bench_cfg, profile)
    monitor = ResourceMonitor(float(bench_cfg.get("resource_sample_interval", 0.5)))
    # Erst der Monitor (wartet ggf. bis zu 15 s auf eine ruhige GPU), dann die
    # Zeitmessung - sonst zaehlt die Wartezeit zur Benchmark-Dauer.
    monitor.start()
    started = time.perf_counter()
    load_warning: str | None = None

    stdout, stderr, returncode, timed_out = _execute(args, timeout_s, monitor, on_progress)

    if returncode != 0 and not timed_out and _rejected_progress(stdout, stderr):
        args = _test_args(
            _base_args(exe, model_path, bench_cfg, profile, with_progress=False),
            bench_cfg, test_kind,
        )
        if on_progress:
            on_progress("Build kennt --progress nicht, Wiederholung ohne Fortschrittsanzeige", None)
        stdout, stderr, returncode, timed_out = _execute(args, timeout_s, monitor, on_progress)

    if returncode != 0 and not timed_out and _rejected_no_mmap(stdout, stderr):
        args = _test_args(
            _base_args(exe, model_path, bench_cfg, profile, with_progress=False, with_no_mmap=False),
            bench_cfg, test_kind,
        )
        load_warning = _(
            "Dieser llama.cpp-Build lehnt das Laden ohne mmap ab. Der Test laeuft deshalb mit mmap; "
            "CPU-Werte sind nicht direkt mit Laeufen ohne mmap vergleichbar."
        )
        if on_progress:
            on_progress(load_warning, None)
        stdout, stderr, returncode, timed_out = _execute(args, timeout_s, monitor, on_progress)

    duration = time.perf_counter() - started
    telemetry = monitor.stop()

    raw = {
        "started_at": utc_now_iso(),
        "duration_seconds": duration,
        "command": args,
        "timeout_seconds": timeout_s,
        "timed_out": timed_out,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "telemetry": telemetry,
    }
    if load_warning:
        raw["warnings"] = [load_warning]
    write_json(output_dir / f"raw_{test_kind}.json", raw)

    light = strip_samples(telemetry)

    if timed_out:
        if test_kind == "long_context":
            partial_rows = _extract_partial_json_rows(stdout)
            if partial_rows:
                meta = _long_context_failure_metadata(
                    partial_rows,
                    bench_cfg,
                    stderr,
                    timed_out=True,
                    timeout_s=timeout_s,
                )
                completed = set(meta["completed_context_depths"])
                partial_rows = [
                    row
                    for row in partial_rows
                    if int(row.get("n_depth") or 0) in completed
                ]
                if partial_rows:
                    return {
                        "kind": test_kind,
                        "status": "partial",
                        "rows": partial_rows,
                        "error": meta["message"],
                        "duration_seconds": duration,
                        "stderr_tail": (stderr or "")[-4000:],
                        "telemetry": light,
                        "completed_context_depths": meta["completed_context_depths"],
                        "failed_context_depth": meta["failed_context_depth"],
                        "limit_status": meta["limit_status"],
                        "capacity_limited": False,
                        "timed_out": True,
                        "warnings": [meta["message"]],
                    }
        return {
            "kind": test_kind,
            "status": "timeout",
            "error": _timeout_message(test_kind, profile, timeout_s),
            "duration_seconds": duration,
            "stderr_tail": (stderr or "")[-4000:],
            "telemetry": light,
        }
    if returncode != 0:
        err_detail = (stderr or "").strip()[-2000:]
        if test_kind == "long_context":
            partial_rows = _extract_partial_json_rows(stdout)
            if partial_rows:
                meta = _long_context_failure_metadata(partial_rows, bench_cfg, stderr)
                completed = set(meta["completed_context_depths"])
                partial_rows = [
                    row
                    for row in partial_rows
                    if int(row.get("n_depth") or 0) in completed
                ]
                if not partial_rows:
                    partial_rows = []
                else:
                    return {
                        "kind": test_kind,
                        "status": "partial",
                        "rows": partial_rows,
                    "error": meta["message"],
                    "error_detail": err_detail,
                    "duration_seconds": duration,
                    "stderr_tail": (stderr or "")[-4000:],
                    "telemetry": light,
                    "completed_context_depths": meta["completed_context_depths"],
                    "failed_context_depth": meta["failed_context_depth"],
                    "limit_status": meta["limit_status"],
                        "capacity_limited": meta["capacity_limited"],
                        "warnings": [meta["message"]],
                    }
        return {
            "kind": test_kind,
            "status": "failed",
            "error": f"llama-bench endete mit Code {returncode}",
            "error_detail": err_detail,
            "duration_seconds": duration,
            "stderr_tail": (stderr or "")[-4000:],
            "telemetry": light,
        }
    try:
        rows = _extract_json(stdout)
    except Exception as exc:
        return {
            "kind": test_kind,
            "status": "failed",
            "error": f"JSON-Ausgabe von llama-bench nicht lesbar: {exc}",
            "duration_seconds": duration,
            "stdout_tail": (stdout or "")[-4000:],
            "telemetry": light,
        }
    result: dict[str, Any] = {
        "kind": test_kind,
        "status": "ok",
        "duration_seconds": duration,
        "rows": rows,
        "telemetry": light,
    }
    if load_warning:
        result["warnings"] = [load_warning]
    return result


def flatten_bench_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if result.get("status") not in {"ok", "partial"}:
        return rows
    for row in result.get("rows", []):
        rows.append({
            "test": row.get("test") or _derive_test_name(row),
            "avg_ts": row.get("avg_ts"),
            "stddev_ts": row.get("stddev_ts"),
            "n_prompt": row.get("n_prompt"),
            "n_gen": row.get("n_gen"),
            "n_depth": row.get("n_depth"),
            "n_threads": row.get("n_threads"),
            "n_gpu_layers": row.get("n_gpu_layers"),
            "backend": row.get("backends") or row.get("backend"),
            "model_type": row.get("model_type"),
            "model_n_params": row.get("model_n_params"),
            "model_size": row.get("model_size"),
            "build_commit": row.get("build_commit"),
            "build_number": row.get("build_number"),
            "cpu_info": row.get("cpu_info"),
            "gpu_info": row.get("gpu_info"),
        })
    return rows


def build_ids_from_rows(result: dict[str, Any]) -> set[str]:
    """Build-Kennungen, die llama-bench selbst in jede Ergebniszeile schreibt."""
    out: set[str] = set()
    for row in flatten_bench_rows(result):
        commit = row.get("build_commit")
        number = row.get("build_number")
        if commit or number:
            out.add(f"{commit or '?'}/{number or '?'}")
    return out


def _derive_test_name(row: dict[str, Any]) -> str:
    p = int(row.get("n_prompt") or 0)
    n = int(row.get("n_gen") or 0)
    d = int(row.get("n_depth") or 0)
    if p and not n:
        base = f"pp{p}"
    elif n and not p:
        base = f"tg{n}"
    elif p and n:
        base = f"pg{p}+{n}"
    else:
        base = "unknown"
    return f"{base}@d{d}" if d else base
