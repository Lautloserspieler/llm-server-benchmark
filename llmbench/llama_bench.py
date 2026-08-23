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
from .monitor import ResourceMonitor, strip_samples
from .utils import (
    csv_value,
    file_fingerprint,
    kill_process_tree,
    read_json,
    resolve_executable,
    run_capture,
    utc_now_iso,
    write_json,
)


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
    # llama-bench kennt kein --version. Die Buildnummer steht ohnehin in
    # jeder Ergebniszeile (build_commit/build_number); hier interessiert,
    # welche Backends und Geraete der Build auf diesem Rechner sieht.
    try:
        cp = run_capture([resolved, "--list-devices"], timeout=30)
        text = ((cp.stdout or "") + (cp.stderr or "")).strip()
        info["devices_output"] = text[:600]
        info["devices_probe_returncode"] = cp.returncode
    except Exception as exc:
        info["devices_output"] = f"nicht ermittelbar: {exc}"

    # Vom Setup-Skript hinterlegte Build-Metadaten, falls vorhanden.
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
    if with_progress:
        # Meldet, bei welcher Wiederholung llama-bench gerade ist. Ohne das
        # bleibt die Anzeige waehrend langer Tests stumm. Aeltere Builds
        # kennen die Option nicht; run_llama_bench faengt das ab.
        args.append("--progress")
    threads = profile.get("threads", "auto")
    if threads not in (None, "auto", -1):
        args.extend(["-t", str(threads)])
    if profile.get("cpu_moe_layers") is not None:
        args.extend(["-ncmoe", str(profile["cpu_moe_layers"])])
    if profile.get("no_kv_offload"):
        args.extend(["-nkvo", "1"])
    if profile.get("device"):
        args.extend(["-dev", str(profile["device"])])
    if profile.get("tensor_split"):
        args.extend(["-ts", str(profile["tensor_split"])])
    for item in profile.get("additional_args", []) or []:
        args.append(str(item))
    return args


def _rejected_progress(stdout: str, stderr: str) -> bool:
    text = (stdout or "") + (stderr or "")
    return "--progress" in text and ("invalid parameter" in text or "unknown argument" in text)


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

    # Beide Kanaele nebenlaeufig leeren: sonst blockiert llama-bench, sobald
    # der Puffer eines Kanals vollaeuft, und die Anzeige stuende still.
    readers = [
        threading.Thread(target=_drain, args=(proc.stdout, out_lines, None), daemon=True),
        threading.Thread(target=_drain, args=(proc.stderr, err_lines, _report), daemon=True),
    ]
    for reader in readers:
        reader.start()

    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_process_tree(proc)
        with contextlib.suppress(Exception):
            proc.wait(timeout=30)
    for reader in readers:
        reader.join(timeout=10)

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

    timeout_s = float(bench_cfg.get("timeout_seconds", 3600))
    monitor = ResourceMonitor(float(bench_cfg.get("resource_sample_interval", 0.5)))
    started = time.perf_counter()
    monitor.start()

    stdout, stderr, returncode, timed_out = _execute(args, timeout_s, monitor, on_progress)

    # Aeltere llama.cpp-Builds kennen --progress nicht und lehnen den Aufruf
    # sofort ab. In dem Fall einmal ohne wiederholen, statt den Test zu
    # verlieren.
    if returncode != 0 and not timed_out and _rejected_progress(stdout, stderr):
        args = _test_args(
            _base_args(exe, model_path, bench_cfg, profile, with_progress=False),
            bench_cfg, test_kind,
        )
        if on_progress:
            on_progress("Build kennt --progress nicht, Wiederholung ohne Fortschrittsanzeige", None)
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
    write_json(output_dir / f"raw_{test_kind}.json", raw)

    # Ab hier nur noch die Aggregate weiterreichen: die Rohsamples liegen
    # vollstaendig in raw_*.json und wuerden summary.json sonst sprengen.
    light = strip_samples(telemetry)

    if timed_out:
        return {
            "kind": test_kind,
            "status": "timeout",
            "error": (
                f"llama-bench wurde nach {timeout_s:.0f} s abgebrochen. "
                "Vermutlich passt die Kontexttiefe nicht in den Speicher "
                "(benchmark.timeout_seconds anpassen oder context_depths kuerzen)."
            ),
            "duration_seconds": duration,
            "stderr_tail": (stderr or "")[-4000:],
            "telemetry": light,
        }
    if returncode != 0:
        return {
            "kind": test_kind,
            "status": "failed",
            "error": f"llama-bench endete mit Code {returncode}",
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
    return {
        "kind": test_kind,
        "status": "ok",
        "duration_seconds": duration,
        "rows": rows,
        "telemetry": light,
    }


def flatten_bench_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if result.get("status") != "ok":
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
