import pytest

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


# --------------------------------------------- Branch-Haertung (Issue #123)


def _cap(rows, **extra):
    return build_context_capability({"rows": rows, **extra})


def test_invalid_rows_and_depths_are_ignored():
    rows = ["junk", {"n_depth": None}, {"n_depth": True}, {"n_depth": "x"}, {"n_depth": -4, "n_prompt": 1}]
    capability = _cap(rows)
    assert capability["curve"] == []
    assert capability["maximum_verified_context"] is None


def test_prompt_and_generation_rows_together_verify_a_depth():
    capability = _cap([
        {"n_depth": 4096, "n_prompt": 512, "n_gen": 0, "avg_ts": 900.0},
        {"n_depth": 4096, "n_prompt": 0, "n_gen": 128, "avg_ts": 40.0},
    ])
    (point,) = capability["curve"]
    assert point["result"] == "pass" and point["prefill_tps"] == 900.0 and point["decode_tps"] == 40.0
    assert capability["maximum_verified_context"] == 4096


def test_combined_http_row_uses_server_side_prefill_and_decode_when_missing():
    capability = _cap([{"n_depth": 8192, "n_prompt": 512, "n_gen": 64, "avg_ts": 30.0, "prefill_ts": 800.0, "decode_ts": 35.0}])
    (point,) = capability["curve"]
    assert (point["combined_tps"], point["prefill_tps"], point["decode_tps"]) == (30.0, 800.0, 35.0)
    assert point["result"] == "pass"


def test_combined_row_keeps_separate_prefill_and_decode_measurements():
    capability = _cap([
        {"n_depth": 1024, "n_prompt": 128, "n_gen": 0, "avg_ts": 700.0},
        {"n_depth": 1024, "n_prompt": 0, "n_gen": 32, "avg_ts": 50.0},
        {"n_depth": 1024, "n_prompt": 128, "n_gen": 32, "avg_ts": 20.0, "prefill_ts": 1.0, "decode_ts": 2.0},
    ])
    (point,) = capability["curve"]
    assert (point["prefill_tps"], point["decode_tps"], point["combined_tps"]) == (700.0, 50.0, 20.0)


def test_partial_depth_never_raises_the_maximum_verified_context():
    capability = _cap([
        {"n_depth": 1024, "n_prompt": 128, "n_gen": 32, "avg_ts": 20.0},
        {"n_depth": 4096, "n_prompt": 128, "n_gen": 0, "avg_ts": 20.0},
    ])
    assert capability["maximum_verified_context"] == 1024
    assert [p["result"] for p in capability["curve"]] == ["pass", "partial"]



@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"capacity_limited": True}, "oom"),
        ({"limit_status": "skipped_capacity"}, "oom"),
        ({"limit_status": "timeout"}, "timeout"),
        ({"limit_status": "failed"}, "failed"),
        ({"limit_status": "partial"}, "failed"),
        ({"limit_status": "weird"}, "weird"),
        ({}, "unknown"),
    ],
)
def test_failed_boundary_depth_is_classified(result, expected):
    capability = _cap([], failed_context_depth=16384, **result)
    (point,) = capability["curve"]
    assert point["populated_context"] == 16384 and point["result"] == expected
    assert capability["first_failed_context"] == 16384


def test_failed_boundary_overrides_a_partial_row_but_not_a_passed_one():
    partial = _cap([{"n_depth": 2048, "n_prompt": 64, "n_gen": 0}], failed_context_depth=2048, limit_status="timeout")
    assert partial["curve"][0]["result"] == "timeout"
    passed = _cap(
        [{"n_depth": 2048, "n_prompt": 64, "n_gen": 8, "avg_ts": 1.0}], failed_context_depth=2048, limit_status="timeout"
    )
    assert passed["curve"][0]["result"] == "pass"


def test_requested_depths_are_deduplicated_sorted_and_validated():
    capability = _cap([], requested_context_depths=[8192, "2048", 8192, -1, None, True, "bad"])
    assert capability["requested_context_depths"] == [2048, 8192]
