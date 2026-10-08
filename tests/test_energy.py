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
