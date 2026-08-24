from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, List, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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

class ProjectConfig(BaseModel):
    name: str = "LLM Server Benchmark"
    server_name: Optional[str] = None
    output_dir: str = "results"
    hash_models: bool = True
    hash_tools: bool = True

class ToolsConfig(BaseModel):
    llama_bench: str = "llama-bench"
    llama_server: str = "llama-server"

class BenchmarkConfig(BaseModel):
    repetitions: int = Field(5, ge=1)
    delay_seconds: float = 1.0
    batch_size: int = 2048
    ubatch_size: int = 512
    flash_attention: str = "auto"
    cache_type_k: str = "f16"
    cache_type_v: str = "f16"
    resource_sample_interval: float = 0.5
    timeout_seconds: float = Field(3600.0, gt=0)
    auto_tune: bool = False
    prompt_tokens: List[int] = Field(default_factory=lambda: [512, 4096, 8192])
    generation_tokens: List[int] = Field(default_factory=lambda: [128, 512])
    context_depths: List[int] = Field(default_factory=lambda: [0, 8192, 32768, 65536, 130000])
    long_context_prompt_tokens: int = 512
    long_context_generation_tokens: int = 128

    @field_validator("prompt_tokens", "generation_tokens", "context_depths")
    @classmethod
    def validate_token_lists(cls, v):
        if not v:
            raise ValueError("Liste darf nicht leer sein")
        if any(not isinstance(x, int) or x < 0 for x in v):
            raise ValueError("Alle Eintraege muessen nicht-negative ganze Zahlen sein")
        return v

class EndpointConfig(BaseModel):
    enabled: bool = False
    auto_start: bool = True
    base_url: str = "http://127.0.0.1:8080"
    api_key: Optional[str] = None
    context_size: int = 32768
    parallel_slots: int = 8
    concurrency: List[int] = Field(default_factory=lambda: [1, 2, 4, 8])
    requests_per_level: int = 8
    warmup_requests: int = 2
    max_tokens: int = 256
    temperature: float = 0.0
    seed: int = 42
    ignore_eos: bool = True
    timeout_seconds: int = 600
    startup_timeout_seconds: int = 300
    prompt: str = (
        "Erklaere in einem technisch praezisen Absatz, warum reproduzierbare "
        "Benchmarks fuer lokale LLM-Server wichtig sind."
    )

    @field_validator("concurrency")
    @classmethod
    def validate_concurrency(cls, v):
        if not v:
            raise ValueError("concurrency-Liste darf nicht leer sein")
        if any(not isinstance(x, int) or x < 1 for x in v):
            raise ValueError("Alle concurrency-Werte muessen ganze Zahlen >= 1 sein")
        return v

class ProfileConfig(BaseModel):
    name: str
    gpu_layers: int

class ModelConfig(BaseModel):
    name: str
    path: str
    profiles: List[ProfileConfig]
    quality_gate: Optional[Any] = None
    notes: Optional[str] = None
    endpoint: Optional[dict] = None

class RootConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    benchmark: BenchmarkConfig = Field(default_factory=BenchmarkConfig)
    endpoint: EndpointConfig = Field(default_factory=EndpointConfig)
    models: List[ModelConfig] = Field(default_factory=list)

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
    cfg_dict = deep_merge(DEFAULT_CONFIG, raw)

    # Validierung via Pydantic
    RootConfig(**cfg_dict)

    cfg_dict["_config_path"] = str(p.resolve())
    cfg_dict["_config_dir"] = str(p.resolve().parent)
    return cfg_dict

def public_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Konfiguration ohne interne Felder und ohne Geheimnisse, fuer Ergebnisdateien."""
    out = {k: copy.deepcopy(v) for k, v in cfg.items() if not k.startswith("_")}
    endpoint = out.get("endpoint")
    if isinstance(endpoint, dict) and endpoint.get("api_key"):
        endpoint["api_key"] = "***"
    return out

# Zeit-Presets für die Benchmark-Dauer
DURATION_PRESETS = {
    "short": {
        "repetitions": 2,
        "prompt_tokens": [512, 4096],
        "generation_tokens": [128],
        "context_depths": [0, 8192],
    },
    "medium": {
        "repetitions": 5,
        "prompt_tokens": [512, 4096, 8192],
        "generation_tokens": [128, 512],
        "context_depths": [0, 8192, 32768, 65536, 130000],
    },
    "long": {
        "repetitions": 10,
        "prompt_tokens": [512, 4096, 8192, 16384, 32768],
        "generation_tokens": [128, 512, 1024],
        "context_depths": [0, 8192, 32768, 65536, 131072, 262144],
    },
}

def apply_duration_preset(cfg: dict[str, Any], duration: str) -> dict[str, Any]:
    """Übersteuert Benchmark-Parameter basierend auf einem Zeit-Preset (short, medium, long)."""
    preset = DURATION_PRESETS.get(duration.lower())
    if not preset:
        raise ValueError(f"Ungültige Dauer: {duration}. Erlaubt: short, medium, long")

    # Mergen in den benchmark-Teil der Konfiguration
    cfg["benchmark"] = deep_merge(cfg.get("benchmark", {}), preset)
    return cfg

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

def validate_config(cfg: dict[str, Any]) -> list[str]:
    """Prueft die Konfiguration auf Fehler. Nutzt intern Pydantic fuer die Validierung."""
    try:
        RootConfig(**cfg)
        return []
    except ValidationError as exc:
        errors = []
        for error in exc.errors():
            loc = ".".join(str(x) for x in error["loc"])
            msg = error["msg"]
            errors.append(f"{loc}: {msg}")
        return errors
