from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from llmbench.bootstrap import discover_models, shard_info
from llmbench.config import load_config
from llmbench.llama_bench import flatten_bench_rows, run_llama_bench
from llmbench.utils import ensure_dir, print_err, print_msg, safe_name, write_json

# Typische llama.cpp/GGUF-Quantisierungsnamen. Wichtig ist, dass nur Varianten
# desselben Basis-Modells gegeneinander verglichen werden.
QUANT_RE = re.compile(
    r"(?i)(?:^|[-_.])(?P<quant>(?:I?Q\d(?:_[A-Z0-9]+)+|BF16|F16))(?:[-_.]|$)"
)


def _model_prefix(path: Path) -> str:
    info = shard_info(path)
    return info[0] if info else path.stem


def split_quant_name(path: Path) -> tuple[str, str] | None:
    prefix = _model_prefix(path)
    match = QUANT_RE.search(prefix)
    if not match:
        return None
    quant = match.group("quant").upper()
    start, end = match.span("quant")
    base = (prefix[:start] + prefix[end:]).strip("-_. ")
    base = re.sub(r"[-_.]{2,}", "-", base)
    return base or prefix, quant


def discover_quant_groups(root: Path, models_dir: Path) -> dict[str, dict[str, Path]]:
    grouped: dict[tuple[str, str], dict[str, Path]] = defaultdict(dict)
    for path in discover_models(root, models_dir):
        parsed = split_quant_name(path)
        if not parsed:
            continue
        base, quant = parsed
        key = (str(path.parent.resolve()).lower(), base.lower())
        grouped[key][quant] = path

    out: dict[str, dict[str, Path]] = {}
    for (_parent, _base_lower), variants in grouped.items():
        if len(variants) < 2:
            continue
        first_path = next(iter(variants.values()))
        base = split_quant_name(first_path)[0]
        label = base
        if label in out:
            label = f"{base}-{first_path.parent.name}"
        out[label] = dict(sorted(variants.items()))
    return out


def _best_tps(result: dict) -> float | None:
    values = [float(row["avg_ts"]) for row in flatten_bench_rows(result) if row.get("avg_ts") is not None]
    return max(values) if values else None


async def run_quant_stress(config_path: str = "benchmark.yaml", output_dir: str | Path | None = None) -> int:
    """Vergleicht mindestens zwei Quantisierungen exakt desselben Basismodells."""
    cfg = load_config(config_path)
    root = Path(cfg.get("_config_dir") or ".").resolve()
    models_dir = root / "models"
    groups = discover_quant_groups(root, models_dir)
    if not groups:
        print_err(
            "Kein echter Quantisierungsvergleich moeglich. Lege mindestens zwei Quantisierungen "
            "desselben Modells (z.B. Q4_K_M und Q8_0) unter models/ ab."
        )
        return 1

    default_out = Path(cfg.get("project", {}).get("output_dir", "results")) / "stress_quant"
    out_dir = ensure_dir(Path(output_dir) if output_dir is not None else default_out)
    bench_cfg = dict(cfg["benchmark"])
    bench_cfg["prompt_tokens"] = [512]
    bench_cfg["generation_tokens"] = [128]
    bench_cfg["context_depths"] = [0]
    profile = {"name": "Full-GPU", "gpu_layers": -1, "threads": "auto"}
    exe = cfg["tools"]["llama_bench"]

    document: dict = {"status": "ok", "groups": []}
    any_success = False
    for base_name, variants in groups.items():
        print_msg(f"\n=== Quantisierungsvergleich: {base_name} ===")
        group_result = {"base_model": base_name, "variants": []}
        for quant, model_path in variants.items():
            print_msg(f"Teste {quant}: {model_path.name}")
            variant_dir = ensure_dir(out_dir / safe_name(base_name) / safe_name(quant))
            prompt_result = run_llama_bench(
                exe, str(model_path), bench_cfg, profile, "prompt", variant_dir
            )
            generation_result = run_llama_bench(
                exe, str(model_path), bench_cfg, profile, "generation", variant_dir
            )
            status = "ok" if prompt_result.get("status") == "ok" and generation_result.get("status") == "ok" else "failed"
            any_success = any_success or status == "ok"
            entry = {
                "quant": quant,
                "path": str(model_path),
                "status": status,
                "prompt_tps": _best_tps(prompt_result),
                "generation_tps": _best_tps(generation_result),
                "prompt": prompt_result,
                "generation": generation_result,
            }
            group_result["variants"].append(entry)
            if status == "ok":
                print_msg(
                    f"  {quant}: PP {entry['prompt_tps'] or 0:.2f} t/s, "
                    f"TG {entry['generation_tps'] or 0:.2f} t/s"
                )
            else:
                print_err(f"{quant} konnte nicht vollstaendig gemessen werden.")
        document["groups"].append(group_result)

    if not any_success:
        document["status"] = "failed"
    write_json(out_dir / "quant.json", document)
    print_msg(f"\nStrukturierte Ergebnisse: {out_dir / 'quant.json'}")
    return 0 if any_success else 1
