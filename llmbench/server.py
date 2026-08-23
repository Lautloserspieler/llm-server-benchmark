"""Web-Dashboard fuer llmbench.

Sicherheitsmodell: Der Server bindet standardmaessig an 127.0.0.1 und ist damit
nur lokal erreichbar. Das genuegt allein nicht, weil eine beliebige im Browser
geoeffnete Webseite Anfragen an localhost stellen kann. Zusaetzlich gilt daher:

* Keine CORS-Freigabe (die Oberflaeche laeuft same-origin, sie braucht keine).
* Zustandsaendernde Endpunkte pruefen die Fetch-Metadaten des Browsers und
  lehnen alles ab, was von einer fremden Seite ausgeht.
* Optional ein Token ueber die Umgebungsvariable LLMBENCH_TOKEN; bei Freigabe
  ins Netz (--allow-remote) ist es verpflichtend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import sys
from pathlib import Path
from collections.abc import AsyncGenerator
from typing import Any

import uvicorn
import yaml
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import DEFAULT_CONFIG, deep_merge, normalize_flash_attention, validate_config

# Ruhiger Log auf Windows: der Proactor meldet harmlose WinError 10054.
if sys.platform == "win32":
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)

ALLOWED_ACTIONS = {"bootstrap", "doctor", "run"}
SAFE_FETCH_SITES = {"same-origin", "same-site", "none"}
SAFE_FETCH_DESTS = {"empty", "document"}


class ServerState:
    def __init__(self) -> None:
        self.root = Path(os.getcwd())
        self.config_name = "benchmark.yaml"
        self.token: str | None = None
        self.allow_remote = False

    @property
    def config_path(self) -> Path:
        return self.root / self.config_name

    @property
    def results_dir(self) -> Path:
        try:
            cfg = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
            configured = (cfg.get("project") or {}).get("output_dir") or "results"
        except Exception:
            configured = "results"
        p = Path(configured)
        return p if p.is_absolute() else (self.root / p)


state = ServerState()
app = FastAPI(title="LLM Benchmark API")


def guard(request: Request) -> None:
    """Laesst nur Anfragen der eigenen Oberflaeche durch.

    Ein <img>- oder EventSource-Aufruf von einer fremden Seite traegt
    Sec-Fetch-Site: cross-site und wird hier abgewiesen. Werkzeuge ohne
    Browser senden diese Header nicht und koennen keine CSRF ausloesen.
    """
    site = request.headers.get("sec-fetch-site")
    if site and site not in SAFE_FETCH_SITES:
        raise HTTPException(403, "Zugriff nur aus der llmbench-Oberflaeche.")
    dest = request.headers.get("sec-fetch-dest")
    if dest and dest not in SAFE_FETCH_DESTS:
        raise HTTPException(403, "Zugriff nur aus der llmbench-Oberflaeche.")

    origin = request.headers.get("origin")
    if origin:
        host = origin.split("://")[-1].split(":")[0]
        if host not in {"127.0.0.1", "localhost", "[::1]", "::1"} and not state.allow_remote:
            raise HTTPException(403, f"Herkunft {origin} ist nicht zugelassen.")

    if state.token:
        supplied = request.headers.get("x-llmbench-token") or request.query_params.get("token")
        if not supplied or not secrets.compare_digest(supplied, state.token):
            raise HTTPException(401, "Token fehlt oder ist falsch.")


def _safe_run_dir(run_id: str) -> Path:
    """Verhindert, dass ueber ../ beliebige Dateien gelesen werden."""
    base = state.results_dir.resolve()
    candidate = (base / run_id).resolve()
    if candidate != base and base not in candidate.parents:
        raise HTTPException(400, "Ungueltige Lauf-Kennung.")
    return candidate


@app.get("/api/runs")
def get_runs(_: None = Depends(guard)) -> dict[str, Any]:
    results_dir = state.results_dir
    runs = []
    if results_dir.exists():
        for run_path in sorted(results_dir.iterdir()):
            if not run_path.is_dir():
                continue
            summary_file = run_path / "summary.json"
            if not summary_file.exists():
                continue
            try:
                data = json.loads(summary_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            hardware = data.get("hardware") or {}
            runs.append({
                "id": run_path.name,
                "server_name": data.get("server_name"),
                "started_at": data.get("started_at"),
                "finished_at": data.get("finished_at"),
                "models_count": len(data.get("models", [])),
                "config_fingerprint": data.get("config_fingerprint"),
                "warnings": len(data.get("warnings") or []),
                "hardware": {
                    "cpu": (hardware.get("cpu") or {}).get("name"),
                    "gpus": [g.get("name") for g in hardware.get("gpus", [])],
                },
            })
    runs.sort(key=lambda x: x.get("started_at") or "", reverse=True)
    return {"runs": runs}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, _: None = Depends(guard)) -> Any:
    summary_file = _safe_run_dir(run_id) / "summary.json"
    if not summary_file.exists():
        raise HTTPException(404, "Lauf nicht gefunden.")
    try:
        return json.loads(summary_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(500, f"summary.json nicht lesbar: {exc}") from exc


@app.get("/api/config")
def get_config(_: None = Depends(guard)) -> dict[str, Any]:
    path = state.config_path
    if not path.exists():
        raise HTTPException(404, f"{state.config_name} nicht gefunden.")
    # Einmal lesen, daraus parsen. Frueher wurde das Dateihandle von
    # yaml.safe_load geleert und "raw" war immer ein leerer String.
    text = path.read_text(encoding="utf-8")
    try:
        parsed = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(400, f"YAML nicht lesbar: {exc}") from exc
    return {"config": parsed, "raw": text, "path": str(path)}


@app.post("/api/config")
async def save_config(request: Request, _: None = Depends(guard)) -> dict[str, Any]:
    data = await request.json()
    path = state.config_path

    if "raw" in data:
        text = str(data["raw"])
        if not text.strip():
            raise HTTPException(400, "Leere Konfiguration wird nicht gespeichert.")
        try:
            parsed = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise HTTPException(400, f"YAML nicht lesbar: {exc}") from exc
    elif "config" in data:
        parsed = data["config"]
        if not isinstance(parsed, dict) or not parsed:
            raise HTTPException(400, "Leere Konfiguration wird nicht gespeichert.")
        text = None
    else:
        raise HTTPException(400, "Es fehlt 'config' oder 'raw'.")

    # Das Web-UI schickt fuer Flash Attention ein Boolean. Ungeprueft
    # uebernommen wuerde daraus spaeter das ungueltige Argument "-fa False".
    bench = parsed.get("benchmark")
    if isinstance(bench, dict) and "flash_attention" in bench:
        try:
            bench["flash_attention"] = normalize_flash_attention(bench["flash_attention"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        text = None  # nach Korrektur neu serialisieren

    errors = [e for e in validate_config(deep_merge(DEFAULT_CONFIG, parsed))
              if not e.startswith("Keine Modelle")]
    if errors:
        raise HTTPException(400, "Konfiguration ungueltig: " + "; ".join(errors))

    if path.exists():
        path.with_suffix(path.suffix + ".bak").write_text(
            path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    if text is None:
        text = yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True, width=120)
    path.write_text(text, encoding="utf-8")
    return {"status": "success", "backup": str(path) + ".bak"}


async def run_command_generator(cmd: list[str]) -> AsyncGenerator[str, None]:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(state.root),
    )
    try:
        if process.stdout:
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                yield f"data: {json.dumps({'text': text})}\n\n"
        await process.wait()
        yield f"data: {json.dumps({'exit_code': process.returncode})}\n\n"
    except asyncio.CancelledError:
        try:
            process.terminate()
            await process.wait()
        except Exception:
            pass
        raise


@app.get("/api/actions/{action}")
@app.post("/api/actions/{action}")
async def run_action(action: str, _: None = Depends(guard)) -> StreamingResponse:
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(400, f"Unbekannte Aktion: {action}")
    cmd = [sys.executable, "-u", "-m", "llmbench", action, "--config", state.config_name]
    return StreamingResponse(run_command_generator(cmd), media_type="text/event-stream")


def start_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    config_name: str = "benchmark.yaml",
    allow_remote: bool = False,
) -> None:
    state.root = Path(os.getcwd())
    state.config_name = config_name
    state.allow_remote = allow_remote
    state.token = os.environ.get("LLMBENCH_TOKEN") or None

    if allow_remote:
        if host == "127.0.0.1":
            host = "0.0.0.0"  # noqa: S104 - ausdrueckliche Freigabe durch den Nutzer
        if not state.token:
            state.token = secrets.token_urlsafe(24)
            print("Zugriff aus dem Netz aktiviert. Token fuer diese Sitzung:")
            print(f"  {state.token}")
            print(f"Aufruf: http://<host>:{port}/?token={state.token}")

    web_dist = state.root / "web" / "dist"
    if web_dist.exists():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")
    else:
        print(f"Hinweis: Das gebaute Dashboard fehlt unter {web_dist}.")
        print("Erzeugen mit: cd web && npm install && npm run build")

    print(f"Dashboard laeuft auf http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_server()
