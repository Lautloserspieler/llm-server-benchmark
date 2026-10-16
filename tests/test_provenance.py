from llmbench.provenance import condition_rows

BENCH = {"repetitions": 2, "batch_size": 2048, "ubatch_size": 512,
         "flash_attention": "auto", "cache_type_k": "f16", "cache_type_v": "f16"}


def _labels(summary):
    return [label for label, _ in condition_rows(summary)]


def test_ollama_conditions_do_not_show_llama_cpp_settings():
    summary = {
        "backend": "ollama", "config_fingerprint": "abc", "llmbench_version": "1.6.0",
        "config": {"benchmark": BENCH},
        "tools": {"ollama": {"image": "ollama/ollama:latest", "digest": "sha256:" + "a" * 64}},
    }
    labels = _labels(summary)
    assert "Flash Attention" not in labels
    assert "Batch / UBatch" not in labels
    assert "llama.cpp-Build" not in labels
    rows = dict(condition_rows(summary))
    assert rows["Container-Image"] == "ollama/ollama:latest"
    assert rows["Wiederholungen"] == "2"


def test_llama_cpp_conditions_keep_engine_settings():
    summary = {"backend": "llama_cpp", "config": {"benchmark": BENCH}, "tools": {}}
    labels = _labels(summary)
    assert {"Flash Attention", "Batch / UBatch", "KV-Cache K/V", "llama.cpp-Build"} <= set(labels)
