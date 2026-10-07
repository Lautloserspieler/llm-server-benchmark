from llmbench.context_capability import build_context_capability


def _rows(*depths: int) -> list[dict]:
    rows = []
    for depth in depths:
        rows.extend([
            {"n_prompt": 512, "n_gen": 0, "n_depth": depth, "avg_ts": 1200.0 - depth / 1000},
            {"n_prompt": 0, "n_gen": 128, "n_depth": depth, "avg_ts": 60.0 - depth / 10000},
        ])
    return rows


def test_successful_depths_produce_verified_maximum_and_curve():
    capability = build_context_capability({
        "kind": "long_context",
        "status": "ok",
        "rows": _rows(0, 32768, 65536),
        "requested_context_depths": [0, 32768, 65536],
    })

    assert capability["maximum_verified_context"] == 65536
    assert capability["completed_context_depths"] == [0, 32768, 65536]
    assert capability["requested_context_depths"] == [0, 32768, 65536]
    assert [row["result"] for row in capability["curve"]] == ["pass", "pass", "pass"]
    assert capability["curve"][1]["prefill_tps"] is not None
    assert capability["curve"][1]["decode_tps"] is not None


def test_capacity_boundary_is_preserved_without_claiming_failed_depth_verified():
    capability = build_context_capability({
        "kind": "long_context",
        "status": "partial",
        "rows": _rows(0, 131072),
        "completed_context_depths": [0, 131072],
        "requested_context_depths": [0, 131072, 262144],
        "failed_context_depth": 262144,
        "limit_status": "skipped_capacity",
        "capacity_limited": True,
    })

    assert capability["maximum_verified_context"] == 131072
    assert capability["first_failed_context"] == 262144
    assert capability["curve"][-1]["populated_context"] == 262144
    assert capability["curve"][-1]["result"] == "oom"


def test_timeout_boundary_is_reported_separately_from_capacity():
    capability = build_context_capability({
        "kind": "long_context",
        "status": "partial",
        "rows": _rows(0, 65536),
        "failed_context_depth": 131072,
        "limit_status": "timeout",
        "capacity_limited": False,
    })

    assert capability["maximum_verified_context"] == 65536
    assert capability["curve"][-1]["result"] == "timeout"


def test_incomplete_depth_never_counts_as_verified():
    capability = build_context_capability({
        "kind": "long_context",
        "status": "partial",
        "rows": [
            {"n_prompt": 512, "n_gen": 0, "n_depth": 131072, "avg_ts": 900.0},
        ],
        "failed_context_depth": 131072,
        "limit_status": "timeout",
    })

    assert capability["maximum_verified_context"] is None
    assert capability["completed_context_depths"] == []
    assert capability["curve"][0]["result"] == "timeout"
