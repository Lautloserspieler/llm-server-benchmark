from llmbench.runner import BENCH_KINDS, SOAK_LABELS, _resolve_endpoint_profile, count_tests, filter_profiles_by_hardware


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


# --------------------------------------------------------------------------- filter_profiles_by_hardware

_PROFILES = [
    {"name": "Full-GPU", "gpu_layers": -1},
    {"name": "CPU-Only", "gpu_layers": 0},
    {"name": "Hybrid-30L", "gpu_layers": 30},
]


def test_filter_profiles_both_returns_everything_unchanged():
    assert filter_profiles_by_hardware(_PROFILES, "both") == _PROFILES


def test_filter_profiles_cpu_keeps_only_gpu_layers_zero():
    result = filter_profiles_by_hardware(_PROFILES, "cpu")
    assert [p["name"] for p in result] == ["CPU-Only"]


def test_filter_profiles_gpu_keeps_full_gpu_and_hybrid():
    result = filter_profiles_by_hardware(_PROFILES, "gpu")
    assert [p["name"] for p in result] == ["Full-GPU", "Hybrid-30L"]


def test_filter_profiles_handles_empty_list():
    assert filter_profiles_by_hardware([], "cpu") == []


# --------------------------------------------------------------------------- count_tests(hardware_target=...)

def test_count_tests_hardware_cpu_only_counts_only_cpu_profile():
    models = [{
        "name": "M",
        "profiles": [{"name": "Full-GPU", "gpu_layers": -1}, {"name": "CPU-Only", "gpu_layers": 0}],
    }]
    total = count_tests(_cfg(models), hardware_target="cpu")
    assert total == 1 * len(BENCH_KINDS)


def test_count_tests_hardware_restriction_excludes_soak_even_when_both_profiles_exist():
    models = [{
        "name": "M",
        "profiles": [{"name": "Full-GPU", "gpu_layers": -1}, {"name": "CPU-Only", "gpu_layers": 0}],
    }]
    total_cpu = count_tests(_cfg(models), hardware_target="cpu")
    total_gpu = count_tests(_cfg(models), hardware_target="gpu")
    assert total_cpu == 1 * len(BENCH_KINDS)
    assert total_gpu == 1 * len(BENCH_KINDS)


# --------------------------------------------------------------------------- _resolve_endpoint_profile

def test_resolve_endpoint_profile_defaults_to_first_when_unset():
    profile, note = _resolve_endpoint_profile(_PROFILES, "M", {})
    assert profile["name"] == "Full-GPU"
    assert note is None


def test_resolve_endpoint_profile_matches_by_name():
    profile, note = _resolve_endpoint_profile(_PROFILES, "M", {"profile": "CPU-Only"})
    assert profile["name"] == "CPU-Only"
    assert note is None


def test_resolve_endpoint_profile_falls_back_and_warns_when_name_not_found():
    profile, note = _resolve_endpoint_profile(_PROFILES, "M", {"profile": "Does-Not-Exist"})
    assert profile["name"] == "Full-GPU"
    assert note is not None
    assert "Does-Not-Exist" in note
