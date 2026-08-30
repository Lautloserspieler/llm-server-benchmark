"""llmbench download: Automatisches Herunterladen der Standard-Suite ueber HuggingFace.

Dieses Modul nutzt huggingface_hub, um standardisierte GGUF-Modelle fuer die
Benchmark-Suite automatisiert in das models-Verzeichnis herunterzuladen.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypedDict
import os
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

try:
    from huggingface_hub import snapshot_download
except ImportError:
    snapshot_download = None

from typing import TypedDict

class ModelConfig(TypedDict):
    repo_id: str
    pattern: str

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

class RichTqdm:
    _global_progress = None

    def __init__(self, *args, **kwargs):
        from rich.progress import Progress, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn
        
        if RichTqdm._global_progress is None:
            RichTqdm._global_progress = Progress(
                TextColumn("[bold blue]{task.description}", justify="right"),
                BarColumn(bar_width=None),
                "[progress.percentage]{task.percentage:>3.1f}%",
                "•",
                DownloadColumn(),
                "•",
                TransferSpeedColumn(),
            )
            RichTqdm._global_progress.start()
        
        self.desc = kwargs.get("desc", "Download")
        self.total = kwargs.get("total", 0)
        self.task_id = RichTqdm._global_progress.add_task(self.desc, total=self.total)
        self.n = kwargs.get("initial", 0)

    def update(self, n=1):
        if RichTqdm._global_progress and self.task_id is not None:
            RichTqdm._global_progress.update(self.task_id, advance=n)
            self.n += n

    def close(self):
        pass

    def set_description(self, desc):
        self.desc = desc
        if RichTqdm._global_progress and self.task_id is not None:
            RichTqdm._global_progress.update(self.task_id, description=desc)

    def set_postfix(self, **kwargs):
        pass

    def __iter__(self):
        return iter([])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @classmethod
    def close_all(cls):
        if cls._global_progress:
            cls._global_progress.stop()
            cls._global_progress = None


def get_suite_models(suite: str) -> dict[str, ModelConfig]:
    """Sammelt alle Modelle für die gewünschte Suite."""
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
    """Lädt die Modelle der angegebenen Suite herunter."""
    if snapshot_download is None:
        raise RuntimeError(
            "Das Paket 'huggingface_hub' ist nicht installiert. "
            "Bitte führe 'pip install huggingface_hub' oder das Setup erneut aus."
        )

    import warnings
    warnings.filterwarnings("ignore", message="The `local_dir_use_symlinks` argument is deprecated")

    from llmbench.utils import console, print_panel, print_msg, print_err

    out_dir = Path(models_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    
    token = os.environ.get("HF_TOKEN")
    target_models = get_suite_models(suite)
    
    print_panel(
        f"Zielverzeichnis: {out_dir}\n"
        f"Anzahl Modelle: {len(target_models)}\n"
        f"HF-Cache: Aktiv (bereits geladene Dateien werden übersprungen)",
        title=f"Starte Modell-Download: Suite '{suite}'"
    )

    try:
        for name, config in target_models.items():
            print_msg(f"\n[cyan]Überprüfe/Lade {name} ({config['repo_id']})...[/cyan]")
            try:
                downloaded_path = snapshot_download(
                    repo_id=config["repo_id"],
                    allow_patterns=config["pattern"],
                    local_dir=str(out_dir),
                    local_dir_use_symlinks=False,
                    token=token,
                    tqdm_class=RichTqdm
                )
                print_msg(f"[OK] {name} ist bereit in {downloaded_path}", style="bold green")
            except Exception as e:
                print_err(f"Fehler beim Herunterladen von {name}: {e}")
    finally:
        RichTqdm.close_all()

    print_msg("\nAlle Downloads abgeschlossen!", style="bold blue")
