import json
from pathlib import Path

from llmbench.compare import check_consistency, compare_summaries


def make_summary(
    server: str,
    fingerprint: str = "abc123",
    model_sha: str | None = "deadbeefcafe",
    build: str = "1234abc/4567",
    avg_ts: float | None = 100.0,
    status: str = "ok",
    version: str = "1.2.0",
    profile_settings: dict | None = None,
    endpoint: dict | None = None,
    power: float | None = 200.0,
) -> dict:
    if status == "ok":
        bench = {
            "kind": "generation",
            "status": "ok",
            "rows": [{"n_prompt": 0, "n_gen": 128, "n_depth": 0, "avg_ts": avg_ts,
                      "build_commit": build.split("/")[0]}],
            "telemetry": {"gpus": [{"index": 0, "avg_power_w": power, "max_temperature_c": 70}]},
        }
    else:
        bench = {"kind": "generation", "status": status, "error": "kein VRAM", "telemetry": {}}

    model = {
        "model": {"name": "M", "sha256": model_sha},
        "profiles": [{
            "name": "Full-GPU",
            "settings": profile_settings or {"name": "Full-GPU", "gpu_layers": -1},
            "benchmarks": {"generation": bench},
        }],
    }
    if endpoint:
        model["endpoint"] = endpoint
    return {
        "schema_version": 2,
        "llmbench_version": version,
        "server_name": server,
        "config_fingerprint": fingerprint,
        "tools": {"llama_cpp_build_ids": [build],
                  "llama_bench": {"binary": {"sha256": "aaaa"}}},
        "hardware": {"cpu": {"name": "CPU"}, "memory": {"total_bytes": 8 * 1024**3}, "gpus": []},
        "models": [model],
    }


def _levels(issues, level):
    return [i for i in issues if i["level"] == level]


def test_identical_runs_produce_no_issues():
    assert check_consistency([make_summary("A"), make_summary("B")]) == []


def test_different_benchmark_settings_are_an_error():
    issues = check_consistency([make_summary("A"), make_summary("B", fingerprint="zzz999")])
    errors = _levels(issues, "error")
    assert any(i["topic"] == "Benchmark-Konfiguration" for i in errors)


def test_different_llama_cpp_build_is_an_error():
    issues = check_consistency([make_summary("A"), make_summary("B", build="9999xyz/1")])
    assert any(i["topic"] == "llama.cpp-Build" for i in _levels(issues, "error"))


def test_same_model_name_but_different_file_is_an_error():
    """Genau der Fall, den der SHA256 verhindern soll."""
    issues = check_consistency([make_summary("A"), make_summary("B", model_sha="0000111122")])
    assert any("unterschiedliche GGUF" in i["message"] for i in _levels(issues, "error"))


def test_missing_model_hash_is_a_warning_not_an_error():
    issues = check_consistency([make_summary("A"), make_summary("B", model_sha=None)])
    assert not _levels(issues, "error")
    assert any("SHA256" in i["message"] for i in _levels(issues, "warning"))


def test_different_profile_settings_are_an_error():
    issues = check_consistency([
        make_summary("A"),
        make_summary("B", profile_settings={"name": "Full-GPU", "gpu_layers": 20}),
    ])
    assert any(i["topic"].startswith("Profil") for i in _levels(issues, "error"))


def test_different_llmbench_version_is_only_a_warning():
    issues = check_consistency([make_summary("A"), make_summary("B", version="1.1.1")])
    assert not _levels(issues, "error")
    assert any(i["topic"] == "llmbench-Version" for i in _levels(issues, "warning"))


def test_old_schema_is_flagged():
    old = make_summary("Alt")
    old["schema_version"] = 1
    issues = check_consistency([old, make_summary("Neu")])
    assert any(i["topic"] == "Datenstand" for i in issues)


def test_failed_run_stays_visible_in_comparison(tmp_path: Path):
    """Frueher blieb die Zelle leer und sah aus wie 'nicht gemessen'."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    for d, summary in ((a, make_summary("A")), (b, make_summary("B", status="timeout"))):
        d.mkdir()
        (d / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    report, issues = compare_summaries([a, b], tmp_path / "out")
    html = report.read_text(encoding="utf-8")
    bench_section = html.split("Benchmark-Vergleich")[1].split("<h2>")[0]
    # In jeder Zeile des ausgefallenen Bereichs steht der Ausfall, nicht "nicht getestet".
    assert "Zeitueberschreitung" in bench_section
    assert "nicht getestet" not in bench_section
    assert "tg128" in bench_section

    data = json.loads((tmp_path / "out" / "comparison.json").read_text(encoding="utf-8"))
    statuses = {r["server"]: r["status"] for r in data["records"]}
    assert statuses == {"A": "ok", "B": "timeout"}


def test_comparison_contains_endpoint_and_efficiency(tmp_path: Path):
    endpoint = {
        "status": "ok",
        "levels": [{"concurrency": 4, "system_tps": 210.5, "avg_interactivity_tps": 52.6,
                    "ttft_p50_seconds": 0.12, "ttft_p95_seconds": 0.34,
                    "successful": 8, "requests": 8}],
    }
    a = tmp_path / "a"
    a.mkdir()
    (a / "summary.json").write_text(
        json.dumps(make_summary("A", endpoint=endpoint)), encoding="utf-8"
    )
    report, _ = compare_summaries([a], tmp_path / "out")
    html = report.read_text(encoding="utf-8")
    assert "Endpoint- und Mehrbenutzer-Vergleich" in html
    assert "210.50" in html

    data = json.loads((tmp_path / "out" / "comparison.json").read_text(encoding="utf-8"))
    assert data["endpoint"][0]["concurrency"] == 4
    # 100 Tokens/s bei 200 W
    assert abs(data["efficiency"][0]["tokens_per_watt"] - 0.5) < 1e-9
    assert (tmp_path / "out" / "comparison_endpoint.csv").exists()


def test_missing_ttft_is_not_rendered_as_zero(tmp_path: Path):
    endpoint = {
        "status": "ok",
        "levels": [{"concurrency": 1, "system_tps": 0.0, "avg_interactivity_tps": None,
                    "ttft_p50_seconds": None, "ttft_p95_seconds": None,
                    "successful": 0, "requests": 8}],
    }
    a = tmp_path / "a"
    a.mkdir()
    (a / "summary.json").write_text(
        json.dumps(make_summary("A", endpoint=endpoint)), encoding="utf-8"
    )
    report, _ = compare_summaries([a], tmp_path / "out")
    html = report.read_text(encoding="utf-8")
    endpoint_section = html.split("Endpoint- und Mehrbenutzer-Vergleich")[1].split("<h2>")[0]
    # System-TPS ist echt 0, TTFT dagegen unbekannt und muss als "—" erscheinen.
    assert "0.00</td>" in endpoint_section
    assert "—</td>" in endpoint_section
