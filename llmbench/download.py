"""Automatischer Download der standardisierten GGUF-Benchmark-Modelle."""

from __future__ import annotations

import fnmatch
import os
import shutil
import threading
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, TypedDict

from rich.filesize import decimal
from rich.progress import BarColumn, Progress, ProgressColumn, Task, TextColumn
from rich.text import Text

from .bootstrap import logical_model_path, shard_info, shard_set_complete
from .utils import safe_name

os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

try:
    from huggingface_hub import snapshot_download
except ImportError:
    snapshot_download = None


class ModelConfig(TypedDict):
    repo_id: str
    pattern: list[str]
    filename_hint: str
    estimated_gib: float


MODELS: dict[str, dict[str, ModelConfig]] = {
    "small": {
        "Qwen3-8B": {
            "repo_id": "Qwen/Qwen3-8B-GGUF",
            "pattern": ["*q4_k_m*.gguf", "*Q4_K_M*.gguf", "*q4_K_M*.gguf"],
            "filename_hint": "qwen3-8b",
            "estimated_gib": 6.0,
        },
        "R1-Distill-Qwen-7B": {
            "repo_id": "unsloth/DeepSeek-R1-Distill-Qwen-7B-GGUF",
            "pattern": ["*q4_k_m*.gguf", "*Q4_K_M*.gguf", "*q4_K_M*.gguf"],
            "filename_hint": "deepseek-r1-distill-qwen-7b",
            "estimated_gib": 6.0,
        },
    },
    "mid": {
        "Qwen3.8-27B": {
            "repo_id": "bartowski/Qwen3.8-27B-GGUF",
            "pattern": ["*q4_k_m*.gguf", "*Q4_K_M*.gguf", "*q4_K_M*.gguf"],
            "filename_hint": "qwen3.8-27b",
            "estimated_gib": 18.0,
        },
    },
    "heavy": {
        "Qwen2.5-72B-Instruct": {
            "repo_id": "Qwen/Qwen2.5-72B-Instruct-GGUF",
            "pattern": ["*q4_k_m*.gguf", "*Q4_K_M*.gguf", "*q4_K_M*.gguf"],
            "filename_hint": "qwen2.5-72b-instruct",
            "estimated_gib": 48.0,
        },
        "Mixtral-8x22B": {
            "repo_id": "MaziyarPanahi/Mixtral-8x22B-Instruct-v0.1-GGUF",
            "pattern": ["*q4_k_m*.gguf", "*Q4_K_M*.gguf", "*q4_K_M*.gguf"],
            "filename_hint": "mixtral-8x22b",
            "estimated_gib": 90.0,
        },
    },
}


class _AdaptivePercentColumn(ProgressColumn):
    """Zeigt Prozent nur an, wenn die Gesamtgroesse bereits bekannt ist."""

    def render(self, task: Task) -> Text:
        if task.total is None or task.total <= 0:
            return Text("   -- ")
        return Text(f"{task.percentage:5.1f}%")


class _AdaptiveAmountColumn(ProgressColumn):
    """Zeigt Bytes bei Downloads und Zaehler bei Datei-Tasks an."""

    def render(self, task: Task) -> Text:
        unit = str(task.fields.get("unit") or "it")
        if unit == "B":
            completed = decimal(int(max(0, task.completed)))
            if task.total is None or task.total <= 0:
                return Text(f"{completed} geladen")
            return Text(f"{completed}/{decimal(int(task.total))}")

        completed_count = int(max(0, task.completed))
        if task.total is None or task.total <= 0:
            return Text(str(completed_count))
        return Text(f"{completed_count}/{int(task.total)}")


class _AdaptiveSpeedColumn(ProgressColumn):
    """Zeigt Downloadgeschwindigkeit nur fuer Byte-Tasks an."""

    def render(self, task: Task) -> Text:
        if str(task.fields.get("unit") or "it") != "B":
            return Text("")
        if task.speed is None or task.speed <= 0:
            return Text("--/s")
        return Text(f"{decimal(int(task.speed))}/s")


class RichTqdm:
    """tqdm-kompatible Rich-Bridge fuer ``huggingface_hub``."""

    _global_progress: Progress | None = None
    _lock = threading.RLock()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        from llmbench.utils import console

        self.iterable: Iterable[Any] | None = args[0] if args else kwargs.get("iterable")
        self.desc = str(kwargs.get("desc") or "Download")
        self.unit = str(kwargs.get("unit") or "it")
        self.n = float(kwargs.get("initial") or 0)
        self._total = float(kwargs.get("total") or 0)
        self.disable = bool(kwargs.get("disable", False))
        self.task_id: int | None = None

        if self.disable:
            return

        with self._lock:
            if RichTqdm._global_progress is None:
                RichTqdm._global_progress = Progress(
                    TextColumn("[bold blue]{task.description}", justify="right"),
                    BarColumn(bar_width=None),
                    _AdaptivePercentColumn(),
                    "•",
                    _AdaptiveAmountColumn(),
                    "•",
                    _AdaptiveSpeedColumn(),
                    console=console,
                )
                RichTqdm._global_progress.start()

            self.task_id = RichTqdm._global_progress.add_task(
                self.desc,
                total=self._display_total(self._total),
                completed=self.n,
                unit=self.unit,
            )

    @staticmethod
    def _display_total(value: float | int | None) -> float | None:
        if value is None or value <= 0:
            return None
        return float(value)

    @property
    def total(self) -> float:
        return self._total

    @total.setter
    def total(self, value: float | int | None) -> None:
        self._total = float(value or 0)
        progress = RichTqdm._global_progress
        if progress is None or self.task_id is None:
            return
        with self._lock:
            progress.update(self.task_id, total=self._display_total(value))

    def update(self, n: float | int | None = 1) -> None:
        advance = float(1 if n is None else n)
        self.n += advance
        progress = RichTqdm._global_progress
        if progress is None or self.task_id is None:
            return
        with self._lock:
            progress.update(self.task_id, advance=advance)

    def reset(self, total: float | int | None = None) -> None:
        self.n = 0.0
        if total is not None:
            self._total = float(total)
        progress = RichTqdm._global_progress
        if progress is None or self.task_id is None:
            return
        with self._lock:
            progress.update(self.task_id, completed=0, total=self._display_total(self._total))

    def refresh(self, *_args: Any, **_kwargs: Any) -> None:
        progress = RichTqdm._global_progress
        if progress is not None:
            with self._lock:
                progress.refresh()

    def close(self) -> None:
        self.refresh()

    def set_description(self, desc: str | None = None, refresh: bool = True) -> None:
        self.desc = str(desc or "")
        progress = RichTqdm._global_progress
        if progress is not None and self.task_id is not None:
            with self._lock:
                progress.update(self.task_id, description=self.desc)
        if refresh:
            self.refresh()

    def set_postfix(self, **_kwargs: Any) -> None:
        return None

    def set_postfix_str(self, _text: str, refresh: bool = False) -> None:
        if refresh:
            self.refresh()

    @property
    def format_dict(self) -> dict[str, float]:
        rate = 0.0
        progress = RichTqdm._global_progress
        if progress is not None and self.task_id is not None:
            task = next((item for item in progress.tasks if item.id == self.task_id), None)
            if task is not None and task.speed is not None:
                rate = float(task.speed)
        return {"rate": rate, "n": self.n, "total": self._total}

    def __iter__(self) -> Iterator[Any]:
        if self.iterable is None:
            return
        try:
            for item in self.iterable:
                yield item
                self.update(1)
        finally:
            self.close()

    def __enter__(self) -> RichTqdm:
        return self

    def __exit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        self.close()

    @classmethod
    def get_lock(cls) -> threading.RLock:
        return cls._lock

    @classmethod
    def set_lock(cls, lock: threading.RLock) -> None:
        cls._lock = lock

    @classmethod
    def close_all(cls) -> None:
        with cls._lock:
            if cls._global_progress is not None:
                cls._global_progress.stop()
                cls._global_progress = None


def get_suite_models(suite: str) -> dict[str, ModelConfig]:
    target_models: dict[str, ModelConfig] = {}
    if suite == "all":
        for category in MODELS.values():
            target_models.update(category)
    elif suite in MODELS:
        target_models.update(MODELS[suite])
    else:
        raise ValueError(f"Unbekannte Suite: {suite}. Erlaubt: small, mid, heavy, all.")
    return target_models


def _matches_patterns(filename: str, patterns: list[str]) -> bool:
    lowered = filename.lower()
    return any(fnmatch.fnmatch(lowered, pattern.lower()) for pattern in patterns)


def find_downloaded_model(models_dir: str | Path, config: ModelConfig) -> Path | None:
    """Findet ein vollstaendiges lokales Exemplar eines Manifest-Modells."""
    root = Path(models_dir)
    if not root.exists():
        return None
    hint = config["filename_hint"].lower()
    candidates: set[Path] = set()
    for file_path in root.rglob("*.gguf"):
        name = file_path.name.lower()
        if hint not in name or not _matches_patterns(file_path.name, config["pattern"]):
            continue
        first = logical_model_path(file_path).resolve()
        if shard_info(first) and not shard_set_complete(first):
            continue
        if first.exists():
            candidates.add(first)
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: str(item).lower())[0]


def verify_suite(models_dir: str | Path, suite: str = "all") -> tuple[bool, list[str]]:
    missing = [
        name for name, config in get_suite_models(suite).items()
        if find_downloaded_model(models_dir, config) is None
    ]
    return not missing, missing


def _warn_free_space(out_dir: Path, missing: list[tuple[str, ModelConfig]]) -> None:
    from llmbench.utils import print_msg

    if not missing:
        return
    estimated = sum(config["estimated_gib"] for _name, config in missing)
    try:
        free_gib = shutil.disk_usage(out_dir).free / (1024 ** 3)
    except OSError:
        return
    if free_gib < estimated:
        print_msg(
            f"WARNUNG: ca. {estimated:.0f} GiB koennen fuer die fehlenden Modelle benoetigt werden, "
            f"aber auf dem Ziellaufwerk sind nur {free_gib:.1f} GiB frei.",
            style="bold yellow",
        )


def download_models(models_dir: str | Path, suite: str = "small") -> None:
    """Laedt fehlende Modelle und meldet Erfolg nur bei vollstaendiger Suite."""
    if snapshot_download is None:
        raise RuntimeError(
            "Das Paket 'huggingface_hub' ist nicht installiert. "
            "Bitte fuehre 'pip install huggingface_hub' oder das Setup erneut aus."
        )

    import warnings

    warnings.filterwarnings("ignore", message="The `local_dir_use_symlinks` argument is deprecated")
    from llmbench.utils import print_err, print_msg, print_panel

    out_dir = Path(models_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    token = os.environ.get("HF_TOKEN")
    target_models = get_suite_models(suite)

    missing_before = [
        (name, config) for name, config in target_models.items()
        if find_downloaded_model(out_dir, config) is None
    ]
    _warn_free_space(out_dir, missing_before)

    print_panel(
        f"Zielverzeichnis: {out_dir}\n"
        f"Modelle in Suite: {len(target_models)}\n"
        f"Bereits vollstaendig: {len(target_models) - len(missing_before)}\n"
        "HF-Cache: Aktiv (bereits geladene Dateien werden wiederverwendet)",
        title=f"Starte Modell-Download: Suite '{suite}'",
    )

    failures: list[str] = []
    try:
        for name, config in target_models.items():
            existing = find_downloaded_model(out_dir, config)
            if existing is not None:
                print_msg(f"[OK] {name} bereits vorhanden: {existing}", style="green")
                continue

            print_msg(f"\n[cyan]Lade {name} ({config['repo_id']})...[/cyan]")
            target_dir = out_dir / safe_name(name)
            target_dir.mkdir(parents=True, exist_ok=True)
            try:
                snapshot_download(
                    repo_id=config["repo_id"],
                    allow_patterns=config["pattern"],
                    local_dir=str(target_dir),
                    local_dir_use_symlinks=False,
                    token=token,
                    tqdm_class=RichTqdm,
                )
                found = find_downloaded_model(out_dir, config)
                if found is None:
                    raise RuntimeError(
                        "Download endete ohne ein vollstaendiges passendes GGUF-Modell; "
                        "bei Shard-Modellen muessen alle Teile vorhanden sein."
                    )
                print_msg(f"[OK] {name} ist bereit: {found}", style="bold green")
            except Exception as exc:
                message = f"{name}: {exc}"
                failures.append(message)
                print_err(f"Fehler beim Herunterladen von {message}")
    finally:
        RichTqdm.close_all()

    complete, missing = verify_suite(out_dir, suite)
    if failures or not complete:
        details = failures[:]
        if missing:
            details.append("Fehlende/unvollstaendige Modelle: " + ", ".join(missing))
        raise RuntimeError("Modell-Download unvollstaendig. " + " | ".join(details))

    print_msg("\nAlle Modelle der angeforderten Suite sind vollstaendig vorhanden.", style="bold blue")
