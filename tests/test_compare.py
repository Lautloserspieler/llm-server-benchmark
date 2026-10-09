import json
from pathlib import Path

import pytest

from llmbench.compare import check_consistency, compare_summaries
from llmbench.result_schema import encode_v3


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
    soak: list[dict] | None = None,
    hardware_target: str = "both",
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
    if soak:
        model["soak"] = soak
    return {
        "schema_version": 2,
        "llmbench_version": version,
        "server_name": server,
        "hardware_target": hardware_target,
        "config_fingerprint": fingerprint,
        "tools": {"llama_cpp_build_ids": [build],
                  "llama_bench": {"binary": {"sha256": "aaaa"}}},
        "hardware": {"cpu": {"name": "CPU"}, "memory": {"total_bytes": 8 * 1024**3}, "gpus": []},
        "models": [model],
    }




def _with_energy_efficiency(
    summary: dict,
    *,
    tokens_per_joule: float,
    wh_per_1k_tokens: float,
    component_energy_wh: float,
    coverage: list[str] | None = None,
    power_scope: str = "measured_components",
) -> dict:
    bench = summary["models"][0]["profiles"][0]["benchmarks"]["generation"]
    coverage = coverage or ["cpu_package", "gpu:0"]
    bench["telemetry"]["power"] = {
        "scope": power_scope,
        "coverage": coverage,
        "avg_component_power_w": 525.0,
        "max_component_power_w": 580.0,
        "component_energy_j": component_energy_wh * 3600.0,
        "component_energy_wh": component_energy_wh,
        "wall_power_w": None,
        "wall_energy_j": None,
        "wall_energy_wh": None,
    }
    bench["efficiency"] = {
        "power_scope": power_scope,
        "power_coverage": coverage,
        "token_scope": "generated_tokens",
        "workload_tokens": 4096,
        "tokens_per_joule": tokens_per_joule,
        "joules_per_1k_tokens": 1000.0 / tokens_per_joule,
        "wh_per_1k_tokens": wh_per_1k_tokens,
    }
    return summary

def _levels(issues, level):
    return [i for i in issues if i["level"] == level]


def test_identical_runs_produce_no_issues():
    assert check_consistency([make_summary("A"), make_summary("B")]) == []


def test_v2_and_v3_compare_by_scalar_settings_not_evidence():
    v2 = make_summary("A")
    v3 = encode_v3(make_summary("B"), {("M", "Full-GPU"): "requested"})
    v3["models"][0]["profiles"][0]["settings"]["gpu_layers"]["evidence"]["reference"] = "run-local path"
    assert check_consistency([v2, v3]) == []


def test_different_benchmark_settings_are_an_error():
    issues = check_consistency([make_summary("A"), make_summary("B", fingerprint="zzz999")])
    errors = _levels(issues, "error")
    assert any(i["topic"] == "Benchmark-Konfiguration" for i in errors)


def test_different_hardware_targets_are_an_error():
    issues = check_consistency([
        make_summary("A", hardware_target="gpu"),
        make_summary("B", hardware_target="gpu_overload"),
    ])
    assert any(i["topic"] == "Hardware-Auswahl" for i in _levels(issues, "error"))



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


def test_partial_long_context_keeps_valid_rows_and_marks_missing_depth(tmp_path: Path):
    full = make_summary("A")
    partial = make_summary("B")

    full_bench = {
        "kind": "long_context",
        "status": "ok",
        "rows": [
            {"n_prompt": 0, "n_gen": 128, "n_depth": 131072, "avg_ts": 56.0},
            {"n_prompt": 0, "n_gen": 128, "n_depth": 262144, "avg_ts": 45.0},
        ],
        "telemetry": {},
    }
    partial_bench = {
        "kind": "long_context",
        "status": "partial",
        "rows": [
            {"n_prompt": 0, "n_gen": 128, "n_depth": 131072, "avg_ts": 55.0},
        ],
        "error": "Kontextstufe 262144 konnte nicht erstellt werden.",
        "failed_context_depth": 262144,
        "limit_status": "skipped_capacity",
        "telemetry": {},
    }
    full["models"][0]["profiles"][0]["benchmarks"] = {"long_context": full_bench}
    partial["models"][0]["profiles"][0]["benchmarks"] = {"long_context": partial_bench}

    dirs = []
    for name, summary in (("a", full), ("b", partial)):
        path = tmp_path / name
        path.mkdir()
        (path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        dirs.append(path)

    report, _issues = compare_summaries(dirs, tmp_path / "out")
    html = report.read_text(encoding="utf-8")
    section = html.split("Benchmark-Vergleich")[1].split("<h2>")[0]

    assert "pg0+128@d131072" in section or "tg128@d131072" in section
    assert "55.00" in section
    assert "262144" in section
    assert "Teilweise" in section


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


def test_comparison_contains_soak_results_in_html_and_pdf(tmp_path: Path):
    """Der Soak-Test muss - wie alle anderen Testarten - in HTML und PDF stehen."""
    pytest.importorskip("reportlab")
    pypdf = pytest.importorskip("pypdf")

    soak = [{
        "label": "short",
        "status": "ok",
        "cpu": {"avg_tps": 20.0, "early_window_avg_tps": 21.0, "late_window_avg_tps": 19.0,
                "successful": 8, "requests": 8, "throttling_suspected": False},
        "gpu": {"avg_tps": 90.0, "early_window_avg_tps": 100.0, "late_window_avg_tps": 60.0,
                "successful": 30, "requests": 30, "throttling_suspected": True},
        "telemetry": {"gpus": [{"index": 0, "max_temperature_c": 84.0}]},
    }]
    a = tmp_path / "a"
    a.mkdir()
    (a / "summary.json").write_text(
        json.dumps(make_summary("A", soak=soak)), encoding="utf-8"
    )
    report, _ = compare_summaries([a], tmp_path / "out")
    html = report.read_text(encoding="utf-8")
    assert "Dauerlast-Test (Soak)" in html
    assert "90.0" in html

    pdf_path = tmp_path / "out" / "comparison.pdf"
    assert pdf_path.exists()
    reader = pypdf.PdfReader(str(pdf_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Dauerlast-Test (Soak)" in text
    assert "90.00" in text
    assert "Throttling" in text


# ------------------------------------------------------------ Backend-Vergleich

def _backend_issues(*backends: str | None) -> list[dict]:
    summaries = []
    for i, backend in enumerate(backends):
        summary = make_summary(f"S{i}")
        if backend is not None:
            summary["backend"] = backend
        summaries.append(summary)
    return [i for i in check_consistency(summaries) if i["topic"] == "Backend"]


def test_same_backend_produces_no_issue():
    assert _backend_issues("llama_cpp", "llama_cpp") == []


def test_different_backends_are_an_error():
    """Tokens/s aus llama.cpp und vLLM duerfen nicht wortlos nebeneinanderstehen."""
    issues = _backend_issues("llama_cpp", "vllm")
    assert len(issues) == 1
    assert issues[0]["level"] == "error"
    assert "nicht direkt vergleichbar" in issues[0]["message"]
    # Die konkreten Backends muessen in der Meldung auftauchen.
    assert "llama_cpp" in issues[0]["message"]
    assert "vllm" in issues[0]["message"]


def test_backend_mismatch_is_strict_relevant(tmp_path: Path):
    """--strict muss einen backend-uebergreifenden Vergleich ablehnen."""
    dirs = []
    for name, backend in (("A", "llama_cpp"), ("B", "vllm")):
        d = tmp_path / name
        d.mkdir()
        summary = make_summary(name)
        summary["backend"] = backend
        (d / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        dirs.append(d)

    _report, issues = compare_summaries(dirs, tmp_path / "out")
    errors = [i for i in issues if i["level"] == "error"]
    assert any(i["topic"] == "Backend" for i in errors)


def test_legacy_summaries_without_backend_are_not_flagged():
    """Alte Laeufe kennen das Feld nicht - das darf kein Fehler sein."""
    assert _backend_issues(None, None) == []
    assert _backend_issues("llama_cpp", None) == []


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


def test_compare_uses_persisted_component_energy_efficiency_for_ranking(tmp_path: Path):
    summaries = [
        _with_energy_efficiency(
            make_summary("A"),
            tokens_per_joule=0.15,
            wh_per_1k_tokens=1.85,
            component_energy_wh=40.0,
        ),
        _with_energy_efficiency(
            make_summary("B"),
            tokens_per_joule=0.20,
            wh_per_1k_tokens=1.40,
            component_energy_wh=35.0,
        ),
    ]
    dirs = []
    for name, summary in zip(("a", "b"), summaries, strict=True):
        path = tmp_path / name
        path.mkdir()
        (path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        dirs.append(path)

    report, issues = compare_summaries(dirs, tmp_path / "out")
    assert not any(issue["topic"].startswith("Energie-Messumfang") for issue in issues)

    html = report.read_text(encoding="utf-8")
    assert "Energieeffizienz" in html
    assert "0.2000 tokens/J" in html
    assert "1.4000 Wh/1k tokens" in html
    assert "measured_components: cpu_package, gpu:0" in html

    data = json.loads((tmp_path / "out" / "comparison.json").read_text(encoding="utf-8"))
    by_server = {row["server"]: row for row in data["efficiency"]}
    assert by_server["A"]["tokens_per_joule"] == 0.15
    assert by_server["B"]["tokens_per_joule"] == 0.20
    assert by_server["B"]["component_energy_wh"] == 35.0
    assert data["scores"]["A"]["normalized"]["eff"] == 75.0
    assert data["scores"]["B"]["normalized"]["eff"] == 100.0
    assert (tmp_path / "out" / "comparison_efficiency.csv").exists()


def test_compare_warns_and_does_not_rank_different_energy_scopes(tmp_path: Path):
    a_summary = _with_energy_efficiency(
        make_summary("A"),
        tokens_per_joule=0.15,
        wh_per_1k_tokens=1.85,
        component_energy_wh=40.0,
        coverage=["cpu_package", "gpu:0"],
    )
    b_summary = _with_energy_efficiency(
        make_summary("B"),
        tokens_per_joule=0.30,
        wh_per_1k_tokens=0.90,
        component_energy_wh=20.0,
        coverage=["gpu:0"],
    )
    dirs = []
    for name, summary in (("a", a_summary), ("b", b_summary)):
        path = tmp_path / name
        path.mkdir()
        (path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        dirs.append(path)

    report, issues = compare_summaries(dirs, tmp_path / "out")

    scope_issues = [
        issue for issue in issues
        if issue["topic"].startswith("Energie-Messumfang")
    ]
    assert len(scope_issues) == 1
    assert scope_issues[0]["level"] == "warning"
    assert "cpu_package" in scope_issues[0]["message"]
    assert "gpu:0" in scope_issues[0]["message"]

    data = json.loads((tmp_path / "out" / "comparison.json").read_text(encoding="utf-8"))
    assert data["scores"]["A"]["normalized"]["eff"] is None
    assert data["scores"]["B"]["normalized"]["eff"] is None

    html = report.read_text(encoding="utf-8")
    assert "nicht vergleichbar" in html


def test_legacy_gpu_only_efficiency_stays_informational_and_out_of_score(tmp_path: Path):
    path = tmp_path / "a"
    path.mkdir()
    (path / "summary.json").write_text(
        json.dumps(make_summary("A", avg_ts=100.0, power=200.0)),
        encoding="utf-8",
    )

    report, _issues = compare_summaries([path], tmp_path / "out")
    data = json.loads((tmp_path / "out" / "comparison.json").read_text(encoding="utf-8"))

    record = data["efficiency"][0]
    assert record["tokens_per_joule"] is None
    assert record["legacy_gpu_tokens_per_watt"] == 0.5
    assert record["tokens_per_watt"] == 0.5
    assert data["scores"]["A"]["normalized"]["eff"] is None

    html = report.read_text(encoding="utf-8")
    assert "Legacy GPU-only" in html
    assert "nicht im Score" in html


def test_compare_pdf_contains_persisted_energy_efficiency(tmp_path: Path):
    pytest.importorskip("reportlab")
    pypdf = pytest.importorskip("pypdf")

    summary = _with_energy_efficiency(
        make_summary("A"),
        tokens_per_joule=0.161,
        wh_per_1k_tokens=1.72,
        component_energy_wh=39.8,
    )
    path = tmp_path / "a"
    path.mkdir()
    (path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    compare_summaries([path], tmp_path / "out")

    reader = pypdf.PdfReader(str(tmp_path / "out" / "comparison.pdf"))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Energieeffizienz" in text
    assert "Tokens/J" in text
    assert "0.1610" in text
    assert "1.7200" in text
    assert "39.800 Wh" in text
    assert "measured_components" in text
