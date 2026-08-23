import pytest

from llmbench.config import (
    DEFAULT_CONFIG,
    config_fingerprint,
    deep_merge,
    normalize_flash_attention,
    public_config,
    validate_config,
)


def _valid_cfg(**overrides):
    cfg = {
        "benchmark": dict(DEFAULT_CONFIG["benchmark"]),
        "models": [{"name": "M", "path": "x.gguf", "profiles": [{"name": "GPU", "gpu_layers": -1}]}],
    }
    cfg.update(overrides)
    return cfg


def test_deep_merge():
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 3}}) == {"a": {"b": 3, "c": 2}}


def test_deep_merge_does_not_share_nested_defaults():
    """Ohne Kopie zeigt cfg['benchmark'] auf DEFAULT_CONFIG['benchmark'] und eine
    Aenderung wuerde den Modul-Default fuer den ganzen Prozess veraendern."""
    merged = deep_merge(DEFAULT_CONFIG, {"project": {"name": "X"}})
    assert merged["benchmark"] is not DEFAULT_CONFIG["benchmark"]
    merged["benchmark"]["repetitions"] = 999
    assert DEFAULT_CONFIG["benchmark"]["repetitions"] == 5


def test_validation_accepts_valid_config():
    assert validate_config(_valid_cfg()) == []


def test_validation_rejects_duplicate_model_names():
    cfg = _valid_cfg(models=[
        {"name": "mixtral", "path": "q4/mixtral.gguf", "profiles": [{"name": "GPU", "gpu_layers": -1}]},
        {"name": "mixtral", "path": "q8/mixtral.gguf", "profiles": [{"name": "GPU", "gpu_layers": -1}]},
    ])
    errors = validate_config(cfg)
    assert any("Doppelte Modellnamen" in e for e in errors)


def test_validation_rejects_duplicate_profile_names():
    cfg = _valid_cfg(models=[{
        "name": "M", "path": "x.gguf",
        "profiles": [{"name": "GPU", "gpu_layers": -1}, {"name": "gpu", "gpu_layers": 20}],
    }])
    assert any("eindeutig" in e for e in validate_config(cfg))


def test_validation_rejects_broken_benchmark_values():
    cfg = _valid_cfg()
    cfg["benchmark"]["repetitions"] = 0
    cfg["benchmark"]["prompt_tokens"] = []
    errors = validate_config(cfg)
    assert any("repetitions" in e for e in errors)
    assert any("prompt_tokens" in e for e in errors)


@pytest.mark.parametrize(
    "value,expected",
    [("auto", "auto"), (True, "on"), (False, "off"), ("1", "on"), ("0", "off"), ("OFF", "off")],
)
def test_normalize_flash_attention(value, expected):
    assert normalize_flash_attention(value) == expected


def test_normalize_flash_attention_rejects_garbage():
    with pytest.raises(ValueError):
        normalize_flash_attention("vielleicht")


def test_flash_attention_boolean_does_not_reach_llama_bench():
    """Das Web-UI schickte frueher das Boolean False, woraus '-fa False' wurde."""
    cfg = _valid_cfg()
    cfg["benchmark"]["flash_attention"] = False
    assert validate_config(cfg) == []
    assert normalize_flash_attention(cfg["benchmark"]["flash_attention"]) == "off"


def test_fingerprint_ignores_irrelevant_keys_but_catches_relevant_ones():
    a = dict(DEFAULT_CONFIG["benchmark"])
    b = dict(a, delay_seconds=99, resource_sample_interval=5.0)
    assert config_fingerprint(a) == config_fingerprint(b)

    c = dict(a, repetitions=1)
    assert config_fingerprint(a) != config_fingerprint(c)

    d = dict(a, cache_type_k="q8_0")
    assert config_fingerprint(a) != config_fingerprint(d)


def test_fingerprint_treats_equivalent_flash_attention_values_as_equal():
    a = dict(DEFAULT_CONFIG["benchmark"], flash_attention=True)
    b = dict(DEFAULT_CONFIG["benchmark"], flash_attention="on")
    assert config_fingerprint(a) == config_fingerprint(b)


def test_public_config_redacts_api_key_and_internals():
    cfg = deep_merge(DEFAULT_CONFIG, {"endpoint": {"api_key": "geheim"}})
    cfg["_config_path"] = "/tmp/benchmark.yaml"
    out = public_config(cfg)
    assert out["endpoint"]["api_key"] == "***"
    assert "_config_path" not in out
    assert cfg["endpoint"]["api_key"] == "geheim"
