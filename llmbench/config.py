from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml

# Werte, die das Messergebnis beeinflussen. Nur diese gehen in den
# Konfigurations-Fingerabdruck ein, der zwei Serverlaeufe vergleichbar macht.
FINGERPRINT_KEYS = (
    "repetitions",
    "batch_size",
    "ubatch_size",
    "flash_attention",
    "cache_type_k",
    "cache_type_v",
    "prompt_tokens",
    "generation_tokens",
    "context_depths",
    "long_context_prompt_tokens",
    "long_context_generation_tokens",
)

VALID_FLASH_ATTENTION = {"auto", "on", "off", "0", "1"}

DEFAULT_CONFIG: dict[str, Any] = {
    "project": {
        "name": "LLM Server Benchmark",
        "server_name": None,
        "output_dir": "results",
        "hash_models": True,
        "hash_tools": True,
    },
    "tools": {"llama_bench": "llama-bench", "llama_server": "llama-server"},
    "benchmark": {
        "repetitions": 5,
        "delay_seconds": 1,
        "batch_size": 2048,
        "ubatch_size": 512,
        "flash_attention": "auto",
        "cache_type_k": "f16",
        "cache_type_v": "f16",
        "resource_sample_interval": 0.5,
        "timeout_seconds": 3600,
        "prompt_tokens": [512, 4096, 8192],
        "generation_tokens": [128, 512],
        "context_depths": [0, 8192, 32768, 65536, 130000],
        "long_context_prompt_tokens": 512,
        "long_context_generation_tokens": 128,
    },
    "endpoint": {
        "enabled": False,
        "auto_start": True,
        "base_url": "http://127.0.0.1:8080",
        "api_key": None,
        "context_size": 32768,
        "parallel_slots": 8,
        "concurrency": [1, 2, 4, 8],
        "requests_per_level": 8,
        "warmup_requests": 2,
        "max_tokens": 256,
        "temperature": 0.0,
        "seed": 42,
        "ignore_eos": True,
        "timeout_seconds": 600,
        "startup_timeout_seconds": 300,
        "prompt": (
            "Erklaere in einem technisch praezisen Absatz, warum reproduzierbare "
            "Benchmarks fuer lokale LLM-Server wichtig sind."
        ),
    },
    "models": [],
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge override in base. Verschachtelte Dicts werden kopiert, nie geteilt."""
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def default_config() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_CONFIG)


def load_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    cfg = deep_merge(DEFAULT_CONFIG, raw)
    cfg["_config_path"] = str(p.resolve())
    cfg["_config_dir"] = str(p.resolve().parent)
    return cfg


def public_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Konfiguration ohne interne Felder und ohne Geheimnisse, fuer Ergebnisdateien."""
    out = {k: copy.deepcopy(v) for k, v in cfg.items() if not k.startswith("_")}
    endpoint = out.get("endpoint")
    if isinstance(endpoint, dict) and endpoint.get("api_key"):
        endpoint["api_key"] = "***"
    return out


def normalize_flash_attention(value: Any) -> str:
    """llama.cpp erwartet auto/on/off. Booleans aus dem Web-UI sicher abbilden."""
    if value is True:
        return "on"
    if value is False:
        return "off"
    text = str(value).strip().lower()
    if text in {"true", "yes", "1", "on", "enabled"}:
        return "on"
    if text in {"false", "no", "0", "off", "disabled"}:
        return "off"
    if text == "auto":
        return "auto"
    raise ValueError(
        f"Ungueltiger Wert fuer flash_attention: {value!r}. Erlaubt: auto, on, off."
    )


def config_fingerprint(bench_cfg: dict[str, Any]) -> str:
    """Stabiler Hash ueber genau die Einstellungen, die das Ergebnis beeinflussen."""
    payload = {}
    for key in FINGERPRINT_KEYS:
        value = bench_cfg.get(key)
        if key == "flash_attention":
            try:
                value = normalize_flash_attention(value)
            except ValueError:
                value = str(value)
        payload[key] = value
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def save_example(path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def resolve_path(value: str, cfg: dict[str, Any]) -> str:
    expanded = os.path.expandvars(os.path.expanduser(str(value)))
    p = Path(expanded)
    if p.is_absolute():
        return str(p)
    base = cfg.get("_config_dir") or os.getcwd()
    return str((Path(base) / p).resolve())


def _validate_benchmark(bench: dict[str, Any], errors: list[str]) -> None:
    try:
        if int(bench.get("repetitions", 0)) < 1:
            errors.append("benchmark.repetitions muss mindestens 1 sein.")
    except (TypeError, ValueError):
        errors.append("benchmark.repetitions muss eine ganze Zahl sein.")

    for key in ("prompt_tokens", "generation_tokens", "context_depths"):
        value = bench.get(key)
        if not isinstance(value, list) or not value:
            errors.append(f"benchmark.{key} muss eine nicht leere Liste sein.")
            continue
        for item in value:
            if not isinstance(item, int) or isinstance(item, bool) or item < 0:
                errors.append(f"benchmark.{key} enthaelt einen ungueltigen Wert: {item!r}")
                break

    try:
        normalize_flash_attention(bench.get("flash_attention", "auto"))
    except ValueError as exc:
        errors.append(str(exc))

    try:
        if float(bench.get("timeout_seconds", 0)) <= 0:
            errors.append("benchmark.timeout_seconds muss groesser als 0 sein.")
    except (TypeError, ValueError):
        errors.append("benchmark.timeout_seconds muss eine Zahl sein.")


def validate_config(cfg: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not cfg.get("models"):
        errors.append("Keine Modelle unter 'models' konfiguriert.")

    _validate_benchmark(cfg.get("benchmark") or {}, errors)

    seen_names: dict[str, int] = {}
    for idx, model in enumerate(cfg.get("models", [])):
        name = model.get("name")
        if not name:
            errors.append(f"models[{idx}] hat kein Feld 'name'.")
        else:
            key = str(name).lower()
            if key in seen_names:
                errors.append(
                    f"models[{idx}] heisst '{name}' wie models[{seen_names[key]}]. "
                    "Doppelte Modellnamen ueberschreiben sich gegenseitig im Ergebnisordner."
                )
            else:
                seen_names[key] = idx
        if not model.get("path"):
            errors.append(f"models[{idx}] hat kein Feld 'path'.")

        profiles = model.get("profiles") or []
        if not profiles:
            errors.append(f"models[{idx}] braucht mindestens ein Profil.")
        seen_profiles: dict[str, int] = {}
        for pidx, profile in enumerate(profiles):
            pname = profile.get("name")
            if not pname:
                errors.append(f"models[{idx}].profiles[{pidx}] hat kein Feld 'name'.")
            else:
                pkey = str(pname).lower()
                if pkey in seen_profiles:
                    errors.append(
                        f"models[{idx}].profiles[{pidx}] heisst '{pname}' wie "
                        f"profiles[{seen_profiles[pkey]}]. Profilnamen muessen je Modell eindeutig sein."
                    )
                else:
                    seen_profiles[pkey] = pidx
            if "gpu_layers" not in profile:
                errors.append(f"models[{idx}].profiles[{pidx}] hat kein Feld 'gpu_layers'.")

    endpoint = cfg.get("endpoint") or {}
    if endpoint.get("enabled"):
        levels = endpoint.get("concurrency")
        if not isinstance(levels, list) or not levels:
            errors.append("endpoint.concurrency muss eine nicht leere Liste sein.")
        elif any((not isinstance(x, int)) or isinstance(x, bool) or x < 1 for x in levels):
            errors.append("endpoint.concurrency darf nur ganze Zahlen ab 1 enthalten.")
    return errors
