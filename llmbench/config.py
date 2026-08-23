from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG: dict[str, Any] = {
    "project": {"name": "LLM Server Benchmark", "server_name": None, "output_dir": "results", "hash_models": True},
    "tools": {"llama_bench": "llama-bench.exe", "llama_server": "llama-server.exe"},
    "benchmark": {
        "repetitions": 5, "delay_seconds": 1, "batch_size": 2048, "ubatch_size": 512,
        "flash_attention": "auto", "cache_type_k": "f16", "cache_type_v": "f16",
        "resource_sample_interval": 0.5, "prompt_tokens": [512, 4096, 8192],
        "generation_tokens": [128, 512], "context_depths": [0, 8192, 32768, 65536, 130000],
        "long_context_prompt_tokens": 512, "long_context_generation_tokens": 128,
    },
    "endpoint": {
        "enabled": False, "auto_start": True, "base_url": "http://127.0.0.1:8080", "api_key": None,
        "context_size": 32768, "parallel_slots": 8, "concurrency": [1, 2, 4, 8], "requests_per_level": 8,
        "max_tokens": 256, "temperature": 0.0, "timeout_seconds": 600, "startup_timeout_seconds": 300,
        "prompt": "Erkläre in einem technisch präzisen Absatz, warum reproduzierbare Benchmarks für lokale LLM-Server wichtig sind.",
    },
    "models": [],
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    cfg = deep_merge(DEFAULT_CONFIG, raw)
    cfg["_config_path"] = str(p.resolve())
    cfg["_config_dir"] = str(p.resolve().parent)
    return cfg


def save_example(path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False, allow_unicode=True), encoding="utf-8")


def resolve_path(value: str, cfg: dict[str, Any]) -> str:
    import os
    expanded = os.path.expandvars(os.path.expanduser(value))
    p = Path(expanded)
    if p.is_absolute():
        return str(p)
    return str((Path(cfg["_config_dir"]) / p).resolve())


def validate_config(cfg: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not cfg.get("models"):
        errors.append("No models configured under 'models'.")
    for idx, model in enumerate(cfg.get("models", [])):
        if not model.get("name"):
            errors.append(f"models[{idx}] is missing 'name'.")
        if not model.get("path"):
            errors.append(f"models[{idx}] is missing 'path'.")
        profiles = model.get("profiles") or []
        if not profiles:
            errors.append(f"models[{idx}] needs at least one profile.")
        for pidx, profile in enumerate(profiles):
            if not profile.get("name"):
                errors.append(f"models[{idx}].profiles[{pidx}] is missing 'name'.")
            if "gpu_layers" not in profile:
                errors.append(f"models[{idx}].profiles[{pidx}] is missing 'gpu_layers'.")
    return errors
