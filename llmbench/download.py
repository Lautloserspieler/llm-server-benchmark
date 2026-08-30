"""llmbench download: Automatisches Herunterladen der Standard-Suite ueber HuggingFace.

Dieses Modul nutzt huggingface_hub, um standardisierte GGUF-Modelle fuer die
Benchmark-Suite automatisiert in das models-Verzeichnis herunterzuladen.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypedDict

try:
    from huggingface_hub import snapshot_download
except ImportError:
    snapshot_download = None


class ModelConfig(TypedDict):
    repo_id: str
    pattern: str


# Die vom Nutzer vorgegebene Standard-Suite:
MODELS: dict[str, dict[str, ModelConfig]] = {
    "small": {
        "Qwen3-8B": {"repo_id": "Qwen/Qwen3-8B-GGUF", "pattern": "*q4_k_m*.gguf"},
        "R1-Distill-Qwen-7B": {"repo_id": "unsloth/DeepSeek-R1-Distill-Qwen-7B-GGUF", "pattern": "*Q4_K_M*.gguf"},
    },
    "mid": {
        "Qwen3.8-27B": {"repo_id": "bartowski/Qwen3.8-27B-GGUF", "pattern": "*Q4_K_M*.gguf"},
    },
    "heavy": {
        "Qwen2.5-72B-Instruct": {"repo_id": "Qwen/Qwen2.5-72B-Instruct-GGUF", "pattern": "*q4_k_m*.gguf"},
        "Mixtral-8x22B": {"repo_id": "MaziyarPanahi/Mixtral-8x22B-Instruct-v0.1-GGUF", "pattern": "*Q4_K_M*.gguf"},
    },
}


def get_suite_models(suite: str) -> dict[str, ModelConfig]:
    """Sammelt alle Modelle fuer die gewuenschte Suite."""
    target_models: dict[str, ModelConfig] = {}
    if suite == "all":
        for cat in MODELS.values():
            target_models.update(cat)
    elif suite in MODELS:
        target_models.update(MODELS[suite])
    else:
        raise ValueError(f"Unbekannte Suite: {suite}. Erlaubt: small, mid, heavy, all.")
    return target_models


def download_models(models_dir: str | Path, suite: str = "small") -> None:
    """Laedt die Modelle der angegebenen Suite herunter."""
    if snapshot_download is None:
        raise RuntimeError(
            "Das Paket 'huggingface_hub' ist nicht installiert. "
            "Bitte fuehre 'pip install huggingface_hub' oder das Setup erneut aus."
        )

    import warnings
    warnings.filterwarnings("ignore", message="The `local_dir_use_symlinks` argument is deprecated")
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

    from llmbench.utils import console, print_panel, print_msg, print_err

    out_dir = Path(models_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    
    token = os.environ.get("HF_TOKEN")
    target_models = get_suite_models(suite)
    
    print_panel(
        f"Zielverzeichnis: {out_dir}\n"
        f"Anzahl Modelle: {len(target_models)}\n"
        f"HF-Cache: Aktiv (bereits geladene Dateien werden uebersprungen)",
        title=f"Starte Modell-Download: Suite '{suite}'"
    )

    for name, config in target_models.items():
        with console.status(f"[cyan]Ueberpruefe/Lade {name} ({config['repo_id']})...[/cyan]", spinner="dots"):
            try:
                downloaded_path = snapshot_download(
                    repo_id=config["repo_id"],
                    allow_patterns=config["pattern"],
                    local_dir=str(out_dir),
                    local_dir_use_symlinks=False,
                    token=token,
                )
                print_msg(f"[OK] {name} ist bereit in {downloaded_path}", style="bold green")
            except Exception as e:
                print_err(f"Fehler beim Herunterladen von {name}: {e}")

    print_msg("\nAlle Downloads abgeschlossen!", style="bold blue")
