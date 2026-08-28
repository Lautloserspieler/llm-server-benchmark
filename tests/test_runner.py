from llmbench.runner import BENCH_KINDS, SOAK_LABELS, count_tests


def _cfg(models, soak_enabled=True):
    return {"models": models, "soak": {"enabled": soak_enabled}}


def test_count_tests_adds_soak_labels_when_both_profiles_present():
    models = [{
        "name": "M",
        "profiles": [{"name": "Full-GPU", "gpu_layers": -1}, {"name": "CPU-Only", "gpu_layers": 0}],
    }]
    total = count_tests(_cfg(models))
    assert total == 2 * len(BENCH_KINDS) + len(SOAK_LABELS)


def test_count_tests_skips_soak_without_a_cpu_profile():
    models = [{"name": "M", "profiles": [{"name": "Full-GPU", "gpu_layers": -1}]}]
    total = count_tests(_cfg(models))
    assert total == 1 * len(BENCH_KINDS)


def test_count_tests_skips_soak_when_disabled():
    models = [{
        "name": "M",
        "profiles": [{"name": "Full-GPU", "gpu_layers": -1}, {"name": "CPU-Only", "gpu_layers": 0}],
    }]
    total = count_tests(_cfg(models, soak_enabled=False))
    assert total == 2 * len(BENCH_KINDS)


def test_count_tests_respects_selected_model_filter():
    models = [
        {"name": "A", "profiles": [{"name": "GPU", "gpu_layers": -1}]},
        {"name": "B", "profiles": [{"name": "GPU", "gpu_layers": -1}, {"name": "CPU", "gpu_layers": 0}]},
    ]
    total = count_tests(_cfg(models), selected_model="a")
    assert total == 1 * len(BENCH_KINDS)
