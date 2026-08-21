from llmbench.config import deep_merge, validate_config


def test_deep_merge():
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 3}}) == {"a": {"b": 3, "c": 2}}


def test_validation():
    cfg = {"models": [{"name": "M", "path": "x.gguf", "profiles": [{"name": "GPU", "gpu_layers": -1}]}]}
    assert validate_config(cfg) == []
