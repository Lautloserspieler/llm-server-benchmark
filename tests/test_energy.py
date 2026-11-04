from llmbench.energy import apply_energy_efficiency


def test_generation_efficiency_uses_generated_tokens_and_measured_component_energy():
    result = {
        "kind": "generation",
        "status": "ok",
        "rows": [
            {"n_gen": 128, "samples_ts": [10.0, 11.0, 12.0]},
            {"n_gen": 256, "repetitions": 2},
        ],
        "telemetry": {
            "power": {
                "scope": "measured_components",
                "coverage": ["cpu_package", "gpu:0"],
                "component_energy_j": 1024.0,
            }
        },
    }

    apply_energy_efficiency(result, default_repetitions=9)

    efficiency = result["efficiency"]
    assert efficiency["token_scope"] == "generated_tokens"
    assert efficiency["workload_tokens"] == 896
    assert efficiency["power_scope"] == "measured_components"
    assert efficiency["power_coverage"] == ["cpu_package", "gpu:0"]
    assert efficiency["tokens_per_joule"] == 0.875
    assert efficiency["joules_per_1k_tokens"] == 1024.0 * 1000.0 / 896
    assert efficiency["wh_per_1k_tokens"] == (1024.0 / 3600.0) * 1000.0 / 896


def test_prompt_efficiency_can_use_configured_repetition_fallback():
    result = {
        "kind": "prompt",
        "status": "ok",
        "rows": [{"n_prompt": 512}],
        "telemetry": {
            "power": {
                "coverage": ["gpu:0"],
                "component_energy_j": 256.0,
            }
        },
    }

    apply_energy_efficiency(result, default_repetitions=4)

    assert result["efficiency"]["token_scope"] == "prompt_tokens"
    assert result["efficiency"]["workload_tokens"] == 2048
    assert result["efficiency"]["tokens_per_joule"] == 8.0


def test_long_context_does_not_claim_efficiency_without_defined_work_accounting():
    result = {
        "kind": "long_context",
        "status": "ok",
        "rows": [{"n_prompt": 512, "n_gen": 128, "n_depth": 32768, "repetitions": 3}],
        "telemetry": {"power": {"component_energy_j": 100.0}},
    }

    apply_energy_efficiency(result, default_repetitions=3)

    assert "efficiency" not in result


def test_efficiency_is_omitted_when_energy_is_missing_or_result_is_partial():
    missing = {
        "kind": "generation",
        "status": "ok",
        "rows": [{"n_gen": 128, "repetitions": 3}],
        "telemetry": {"power": {"component_energy_j": None}},
    }
    apply_energy_efficiency(missing, default_repetitions=3)
    assert "efficiency" not in missing

    partial = {
        "kind": "generation",
        "status": "partial",
        "rows": [{"n_gen": 128, "repetitions": 3}],
        "telemetry": {"power": {"component_energy_j": 100.0}},
    }
    apply_energy_efficiency(partial, default_repetitions=3)
    assert "efficiency" not in partial



def test_exact_backend_workload_tokens_override_configured_token_count():
    result = {
        "kind": "prompt",
        "status": "ok",
        "rows": [
            {
                "n_prompt": 512,
                "repetitions": 3,
                "workload_tokens": 1605,
            }
        ],
        "telemetry": {
            "power": {
                "coverage": ["gpu:0"],
                "component_energy_j": 321.0,
            }
        },
    }

    apply_energy_efficiency(result, default_repetitions=3)

    assert result["efficiency"]["workload_tokens"] == 1605
    assert result["efficiency"]["tokens_per_joule"] == 5.0


# --------------------------------------------- Branch-Haertung (Issue #123)


def _ok_result(kind="generation", energy_j=100.0, rows=None, **extra):
    return {
        "status": "ok",
        "kind": kind,
        "telemetry": {"power": {"component_energy_j": energy_j, "coverage": ["gpu:0"]}},
        "rows": rows if rows is not None else [{"n_gen": 10}],
        **extra,
    }


def test_efficiency_uses_sample_count_then_explicit_repetitions_then_default():
    by_samples = _ok_result(rows=[{"n_gen": 10, "samples_ts": [1, 2, 3]}])
    by_rep = _ok_result(rows=[{"n_gen": 10, "repetitions": 4}])
    by_default = _ok_result(rows=[{"n_gen": 10}])
    for result in (by_samples, by_rep, by_default):
        apply_energy_efficiency(result, default_repetitions=2)
    assert by_samples["efficiency"]["workload_tokens"] == 30
    assert by_rep["efficiency"]["workload_tokens"] == 40
    assert by_default["efficiency"]["workload_tokens"] == 20


def test_efficiency_ignores_invalid_repetition_hints():
    result = _ok_result(rows=[{"n_gen": 10, "repetitions": True}, {"n_gen": 5, "repetitions": 0}])
    apply_energy_efficiency(result, default_repetitions=3)
    assert result["efficiency"]["workload_tokens"] == 45


def test_efficiency_skipped_without_any_repetition_information():
    result = _ok_result(rows=[{"n_gen": 10}])
    apply_energy_efficiency(result, default_repetitions=0)
    assert "efficiency" not in result


def test_efficiency_prefers_exact_workload_tokens_and_skips_invalid_rows():
    result = _ok_result(rows=["junk", {"workload_tokens": 50}, {"workload_tokens": True, "n_gen": 4}, {"n_gen": -1}])
    apply_energy_efficiency(result)
    assert result["efficiency"]["workload_tokens"] == 54


def test_efficiency_not_claimed_without_valid_energy_or_work():
    cases = [
        _ok_result(energy_j=0.0),
        _ok_result(energy_j=-5.0),
        _ok_result(energy_j=True),
        _ok_result(energy_j=None),
        _ok_result(rows=[]),
        _ok_result(rows=[{"n_gen": 0}]),
        _ok_result(kind="long_context"),
        {**_ok_result(), "status": "partial"},
    ]
    for result in cases:
        apply_energy_efficiency(result)
        assert "efficiency" not in result, result
