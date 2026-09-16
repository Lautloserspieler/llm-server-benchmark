"""Generische Docker-Bausteine fuer container-basierte Benchmark-Backends.

Bewusst ueber den ``docker``-CLI-Prozess implementiert (kein zusaetzliches SDK),
passend zum Subprocess-Stil aus ``llama_cpp_setup.py`` und ``hardware.py``.

Netzwerk: standardmaessig Bridge-Netzwerk plus Port-Publishing. Das funktioniert
identisch unter Docker Desktop (Windows/macOS, WSL2) und nativem Linux-Docker.

Zukuenftige Optimierung (bewusst noch nicht implementiert): auf nativem
Linux-Docker vermeidet ``--network host`` den NAT-Overhead und liefert damit
etwas praezisere TTFT-Messungen. Das braucht aber eine verlaessliche Erkennung,
ob Host-Networking ueberhaupt verfuegbar ist (unter Docker Desktop ist es das
nicht), plus einen sauberen Fallback auf Bridge. Bis dahin gilt: lieber
durchgehend korrekt und portabel als punktuell schneller.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

LogFn = Callable[[str], None]

# Ein Pull kann bei vLLM-Images mehrere GB umfassen.
PULL_TIMEOUT_SECONDS = 3600.0
DEFAULT_TIMEOUT_SECONDS = 120.0
INSPECT_TIMEOUT_SECONDS = 30.0

# Gleiche Konvention wie compose.yaml: LLMBENCH_GPU_DEVICES speist
# NVIDIA_VISIBLE_DEVICES, "all" bedeutet alle sichtbaren GPUs.
GPU_DEVICES_ENV = "LLMBENCH_GPU_DEVICES"
NVIDIA_DRIVER_CAPABILITIES = "compute,utility"


def _noop(_msg: str) -> None:
    return None


def docker_exe() -> str | None:
    """Pfad zum docker-Binary, oder None wenn es nicht im PATH liegt."""
    return shutil.which("docker")


def docker_available() -> bool:
    """True, wenn das docker-CLI existiert *und* der Daemon erreichbar ist.

    Ein vorhandenes Binary allein genuegt nicht: unter Docker Desktop ist die
    CLI auch dann installiert, wenn die VM gerade nicht laeuft.
    """
    exe = docker_exe()
    if not exe:
        return False
    try:
        proc = subprocess.run(
            [exe, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
    except Exception:
        return False
    return proc.returncode == 0


def _require_docker() -> str:
    exe = docker_exe()
    if not exe:
        raise RuntimeError(
            "Docker wurde nicht gefunden. Die Backends vLLM/Ollama/TGI laufen ausschliesslich "
            "als Container; installiere Docker (Linux) bzw. Docker Desktop (Windows/macOS) "
            "und fuer GPU-Zugriff zusaetzlich das NVIDIA Container Toolkit."
        )
    return exe


def _run(
    args: list[str],
    log: LogFn | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """docker-Aufruf mit einheitlicher Protokollierung und Fehlerbehandlung."""
    log = log or _noop
    exe = _require_docker()
    cmd = [exe, *args]
    log("$ " + " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"docker-Befehl hat das Zeitlimit ueberschritten: {' '.join(cmd)}") from exc

    if check and proc.returncode != 0:
        detail = ((proc.stderr or "") + (proc.stdout or "")).strip()[-2000:]
        raise RuntimeError(f"docker-Befehl fehlgeschlagen ({proc.returncode}): {' '.join(cmd)}\n{detail}")
    return proc


def _run_tolerant(args: list[str], log: LogFn | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> bool:
    """Wie _run, aber ein Fehlschlag wird nur protokolliert.

    Fuer Aufraeumschritte: `uninstall-backend` muss auch dann durchlaufen, wenn
    ein Container oder Image gar nicht (mehr) existiert.
    """
    log = log or _noop
    try:
        proc = _run(args, log=log, timeout=timeout, check=False)
    except RuntimeError as exc:
        log(str(exc))
        return False
    if proc.returncode != 0:
        detail = ((proc.stderr or "") + (proc.stdout or "")).strip().splitlines()
        log("   " + (detail[0] if detail else f"Rueckgabecode {proc.returncode}"))
        return False
    return True


# --------------------------------------------------------------------- Images


def pull_image(image: str, log: LogFn | None = None) -> None:
    """Laedt ein Image herunter. Ein bereits vorhandenes Image wird aktualisiert."""
    log = log or _noop
    log(f"Lade Docker-Image {image} ...")
    _run(["pull", image], log=log, timeout=PULL_TIMEOUT_SECONDS)
    log(f"Docker-Image {image} ist vorhanden.")


def image_exists(image: str) -> bool:
    """True, wenn das Image lokal vorliegt (ohne Netzwerkzugriff)."""
    if not docker_exe():
        return False
    try:
        proc = _run(["image", "inspect", "--format", "{{.Id}}", image],
                    timeout=INSPECT_TIMEOUT_SECONDS, check=False)
    except RuntimeError:
        return False
    return proc.returncode == 0


def image_digest(image: str) -> str | None:
    """RepoDigest des Images - die exakte Werkzeug-Identitaet fuer summary.json.

    Erfuellt fuer Container-Backends dieselbe Rolle wie der Datei-Hash von
    llama-bench: ohne sie laesst sich nicht belegen, dass zwei Laeufe wirklich
    dieselbe Serverversion gemessen haben. Ein lokal gebautes Image hat keinen
    RepoDigest; dann wird auf die Image-ID zurueckgefallen.
    """
    if not docker_exe():
        return None
    try:
        proc = _run(["image", "inspect", "--format", "{{json .RepoDigests}}", image],
                    timeout=INSPECT_TIMEOUT_SECONDS, check=False)
    except RuntimeError:
        return None
    if proc.returncode == 0:
        text = (proc.stdout or "").strip()
        import json

        try:
            digests = json.loads(text)
        except (ValueError, TypeError):
            digests = []
        if isinstance(digests, list) and digests:
            return str(digests[0])

    try:
        proc = _run(["image", "inspect", "--format", "{{.Id}}", image],
                    timeout=INSPECT_TIMEOUT_SECONDS, check=False)
    except RuntimeError:
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


def remove_image(image: str, log: LogFn | None = None) -> None:
    """Entfernt ein Image. Fehlt es bereits, ist das kein Fehler."""
    log = log or _noop
    log(f"Entferne Docker-Image {image} ...")
    _run_tolerant(["image", "rm", "-f", image], log=log, timeout=PULL_TIMEOUT_SECONDS)


# ----------------------------------------------------------------- Container


def gpu_device_flag() -> list[str]:
    """`--gpus`-Argumente nach der LLMBENCH_GPU_DEVICES-Konvention aus compose.yaml.

    "all" (Standard) gibt alle GPUs frei, eine Liste wie "0,1" nur die genannten.
    """
    devices = (os.environ.get(GPU_DEVICES_ENV) or "all").strip()
    if not devices or devices.lower() == "all":
        return ["--gpus", "all"]
    if devices.lower() in {"none", "void"}:
        return []
    return ["--gpus", f"device={devices}"]


def run_container(
    name: str,
    image: str,
    args: list[str],
    *,
    gpu: bool = False,
    port_map: dict[int, int] | None = None,
    env: dict[str, str] | None = None,
    volumes: dict[str, str] | None = None,
    network: str | None = None,
    log: LogFn | None = None,
    extra_args: list[str] | None = None,
) -> str:
    """Startet einen Container im Hintergrund und liefert seine Container-ID.

    ``port_map`` bildet Host-Port auf Container-Port ab. ``volumes`` bildet
    Host-Pfad *oder benanntes Volume* auf den Pfad im Container ab.
    """
    log = log or _noop
    cmd: list[str] = ["run", "-d", "--name", name]

    if gpu:
        cmd.extend(gpu_device_flag())
        # Gleiche Konvention wie compose.yaml, damit GPU-Auswahl und
        # Treiber-Faehigkeiten im Backend-Container identisch aussehen.
        devices = (os.environ.get(GPU_DEVICES_ENV) or "all").strip() or "all"
        cmd.extend(["-e", f"NVIDIA_VISIBLE_DEVICES={devices}"])
        cmd.extend(["-e", f"NVIDIA_DRIVER_CAPABILITIES={NVIDIA_DRIVER_CAPABILITIES}"])

    for key, value in (env or {}).items():
        cmd.extend(["-e", f"{key}={value}"])
    for host_port, container_port in (port_map or {}).items():
        cmd.extend(["-p", f"{host_port}:{container_port}"])
    for source, target in (volumes or {}).items():
        cmd.extend(["-v", f"{source}:{target}"])
    if network:
        cmd.extend(["--network", network])
    for item in extra_args or []:
        cmd.append(str(item))

    cmd.append(image)
    cmd.extend(str(x) for x in args)

    proc = _run(cmd, log=log, timeout=DEFAULT_TIMEOUT_SECONDS)
    container_id = (proc.stdout or "").strip().splitlines()
    container_id = container_id[-1] if container_id else name
    log(f"Container {name} gestartet ({container_id[:12]}).")
    return container_id


def stop_container(name_or_id: str, log: LogFn | None = None) -> None:
    """Stoppt und entfernt einen Container. Fehlt er, ist das kein Fehler."""
    log = log or _noop
    log(f"Stoppe Container {name_or_id} ...")
    _run_tolerant(["stop", name_or_id], log=log)
    _run_tolerant(["rm", "-f", name_or_id], log=log)


def container_exists(name_or_id: str) -> bool:
    if not docker_exe():
        return False
    try:
        proc = _run(["container", "inspect", "--format", "{{.Id}}", name_or_id],
                    timeout=INSPECT_TIMEOUT_SECONDS, check=False)
    except RuntimeError:
        return False
    return proc.returncode == 0


def container_pid(name_or_id: str) -> int | None:
    """Host-sichtbare PID des Hauptprozesses im Container, sonst None.

    Nur auf nativem Linux-Docker teilt sich der Container den PID-Namespace mit
    dem Host, sodass ResourceMonitor die Prozesslast zuordnen kann. Unter Docker
    Desktop (Windows/macOS) laeuft der Daemon in einer VM und meldet hier 0 -
    dann wird ohne Ziel-PID gemessen, genau wie ResourceMonitor es ohnehin
    unterstuetzt.
    """
    if not docker_exe():
        return None
    try:
        proc = _run(["container", "inspect", "--format", "{{.State.Pid}}", name_or_id],
                    timeout=INSPECT_TIMEOUT_SECONDS, check=False)
    except RuntimeError:
        return None
    if proc.returncode != 0:
        return None
    try:
        pid = int((proc.stdout or "").strip())
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def container_logs(name_or_id: str, tail: int | None = None) -> str:
    """stdout/stderr des Containers - das Gegenstueck zur llama-server.log."""
    if not docker_exe():
        return ""
    args = ["logs"]
    if tail is not None:
        args.extend(["--tail", str(int(tail))])
    args.append(name_or_id)
    try:
        proc = _run(args, timeout=DEFAULT_TIMEOUT_SECONDS, check=False)
    except RuntimeError as exc:
        return str(exc)
    return ((proc.stdout or "") + (proc.stderr or "")).strip()


# ------------------------------------------------------------------- Volumes


def remove_volume(name: str, log: LogFn | None = None) -> None:
    """Entfernt ein benanntes Volume. Fehlt es, ist das kein Fehler."""
    log = log or _noop
    log(f"Entferne Docker-Volume {name} ...")
    _run_tolerant(["volume", "rm", "-f", name], log=log)


def volume_exists(name: str) -> bool:
    if not docker_exe():
        return False
    try:
        proc = _run(["volume", "inspect", "--format", "{{.Name}}", name],
                    timeout=INSPECT_TIMEOUT_SECONDS, check=False)
    except RuntimeError:
        return False
    return proc.returncode == 0


def info() -> dict[str, Any]:
    """Kurzer Zustandsbericht fuer doctor-artige Ausgaben."""
    return {"docker_cli": docker_exe(), "daemon_reachable": docker_available()}
