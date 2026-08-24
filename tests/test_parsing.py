import subprocess
import sys
from pathlib import Path

from llmbench.llama_bench import _base_args, _extract_json, flatten_bench_rows, run_llama_bench

BENCH_CFG = {
    "repetitions": 3, "delay_seconds": 0, "batch_size": 2048, "ubatch_size": 512,
    "flash_attention": "auto", "cache_type_k": "f16", "cache_type_v": "f16",
    "resource_sample_interval": 0.1, "timeout_seconds": 3,
    "prompt_tokens": [512], "generation_tokens": [128], "context_depths": [0],
    "long_context_prompt_tokens": 512, "long_context_generation_tokens": 128,
}


def test_extract_json_clean():
    data = _extract_json('[{"n_prompt":512,"n_gen":0,"n_depth":0,"avg_ts":100.5,"stddev_ts":1.2}]')
    assert data[0]["avg_ts"] == 100.5


def test_extract_json_with_noise():
    data = _extract_json('notice\n[{"n_prompt":0,"n_gen":128,"n_depth":0,"avg_ts":55.0}]\n')
    assert data[0]["n_gen"] == 128


def test_flat_derives_name():
    result = {"status": "ok", "rows": [{"n_prompt": 0, "n_gen": 512, "n_depth": 8192, "avg_ts": 42.0}]}
    rows = flatten_bench_rows(result)
    assert rows[0]["test"] == "tg512@d8192"


def test_failed_result_yields_no_rows():
    assert flatten_bench_rows({"status": "failed", "error": "x"}) == []


def test_base_args_pass_cache_types_and_normalized_flash_attention():
    args = _base_args("llama-bench", "m.gguf", dict(BENCH_CFG, flash_attention=False),
                      {"gpu_layers": -1})
    assert "-ctk" in args and "-ctv" in args
    assert args[args.index("-fa") + 1] == "off"
    assert "False" not in args


def test_threads_auto_is_not_passed():
    args = _base_args("llama-bench", "m.gguf", BENCH_CFG, {"gpu_layers": -1, "threads": "auto"})
    assert "-t" not in args
    args = _base_args("llama-bench", "m.gguf", BENCH_CFG, {"gpu_layers": -1, "threads": 8})
    assert args[args.index("-t") + 1] == "8"


def test_hanging_bench_is_aborted_by_timeout(tmp_path: Path, monkeypatch):
    """Ohne Timeout haengt ein Lauf bei zu grosser Kontexttiefe unbegrenzt."""
    script = tmp_path / "hang.py"
    script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")

    real_popen = subprocess.Popen

    def fake_popen(_args, **kwargs):
        return real_popen([sys.executable, str(script)], **kwargs)

    monkeypatch.setattr("llmbench.llama_bench.resolve_executable", lambda x: x)
    monkeypatch.setattr("llmbench.llama_bench.subprocess.Popen", fake_popen)

    result = run_llama_bench(
        "llama-bench", "m.gguf", dict(BENCH_CFG, timeout_seconds=2),
        {"gpu_layers": -1}, "generation", tmp_path,
    )
    assert result["status"] == "timeout"
    assert "abgebrochen" in result["error"]
    raw = (tmp_path / "raw_generation.json").read_text(encoding="utf-8")
    assert '"timed_out": true' in raw


def test_telemetry_samples_stay_out_of_the_returned_result(tmp_path: Path, monkeypatch):
    """Sonst landen tausende Samples in summary.json."""
    script = tmp_path / "ok.py"
    script.write_text(
        'print("[{\\"n_prompt\\":0,\\"n_gen\\":128,\\"n_depth\\":0,\\"avg_ts\\":10.0}]")\n',
        encoding="utf-8",
    )
    real_popen = subprocess.Popen

    def fake_popen(_args, **kwargs):
        return real_popen([sys.executable, str(script)], **kwargs)

    monkeypatch.setattr("llmbench.llama_bench.resolve_executable", lambda x: x)
    monkeypatch.setattr("llmbench.llama_bench.subprocess.Popen", fake_popen)

    result = run_llama_bench(
        "llama-bench", "m.gguf", BENCH_CFG, {"gpu_layers": -1}, "generation", tmp_path
    )
    assert result["status"] == "ok"
    assert "samples" not in result["telemetry"]
    assert result["telemetry"]["samples_stored_in"] == "raw_*.json"
    assert '"samples"' in (tmp_path / "raw_generation.json").read_text(encoding="utf-8")
