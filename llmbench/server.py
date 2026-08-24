import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="LLM Benchmark API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _get_results_dir() -> Path:
    return Path(os.getcwd()) / "results"

@app.get("/api/runs")
def get_runs():
    results_dir = _get_results_dir()
    runs = []
    if results_dir.exists():
        for run_path in results_dir.iterdir():
            if run_path.is_dir():
                summary_file = run_path / "summary.json"
                if summary_file.exists():
                    try:
                        with open(summary_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            runs.append({
                                "id": run_path.name,
                                "server_name": data.get("server_name"),
                                "started_at": data.get("started_at"),
                                "finished_at": data.get("finished_at", None),
                                "models_count": len(data.get("models", [])),
                                "hardware": {
                                    "cpu": data.get("hardware", {}).get("cpu", {}).get("name"),
                                    "gpus": [g.get("name") for g in data.get("hardware", {}).get("gpus", [])]
                                }
                            })
                    except Exception:
                        pass
    runs.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    return {"runs": runs}

@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    summary_file = _get_results_dir() / run_id / "summary.json"
    if summary_file.exists():
        try:
            with open(summary_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            return {"error": str(e)}
    return {"error": "Run not found"}

import yaml
import sys
import asyncio
import logging
from typing import AsyncGenerator
from fastapi import Request
from fastapi.responses import StreamingResponse

# Silence harmless WinError 10054 from asyncio Proactor on Windows
if sys.platform == "win32":
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)

@app.get("/api/config")
def get_config():
    config_path = Path(os.getcwd()) / "benchmark.yaml"
    if not config_path.exists():
        return {"error": "benchmark.yaml not found"}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return {"config": yaml.safe_load(f), "raw": f.read()}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/config")
async def save_config(request: Request):
    try:
        data = await request.json()
        config_path = Path(os.getcwd()) / "benchmark.yaml"
        # If 'raw' is provided, we can write the raw string, otherwise dump YAML
        if "raw" in data:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(data["raw"])
        elif "config" in data:
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(data["config"], f, default_flow_style=False, sort_keys=False)
        return {"status": "success"}
    except Exception as e:
        return {"error": str(e)}

async def run_command_generator(cmd: list[str]) -> AsyncGenerator[str, None]:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=os.getcwd()
    )
    try:
        if process.stdout:
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode('utf-8', errors='replace').rstrip('\r\n')
                # Use json to safely escape the string for SSE data payload
                yield f"data: {json.dumps({'text': text})}\n\n"
        
        await process.wait()
        yield f"data: {json.dumps({'exit_code': process.returncode})}\n\n"
    except asyncio.CancelledError:
        # Client disconnected or cancelled, kill the subprocess
        try:
            process.terminate()
            await process.wait()
        except Exception:
            pass
        raise

@app.get("/api/actions/{action}")
async def run_action(action: str):
    if action not in ("bootstrap", "doctor", "run"):
        return {"error": "Invalid action"}
    
    cmd = [sys.executable, "-u", "-m", "llmbench", action, "--config", "benchmark.yaml"]
    return StreamingResponse(run_command_generator(cmd), media_type="text/event-stream")

def start_server(host: str = "127.0.0.1", port: int = 8000):
    web_dist = Path(os.getcwd()) / "web" / "dist"
    if web_dist.exists():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")
    else:
        print(f"Warning: Web dashboard build not found at {web_dist}.")
    print(f"Starting server at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    start_server()
