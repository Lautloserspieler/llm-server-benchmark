import json
from pathlib import Path

import pytest
import yaml

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from llmbench import server as srv  # noqa: E402


@pytest.fixture()
def client(tmp_path: Path):
    (tmp_path / "results" / "RUN_A").mkdir(parents=True)
    (tmp_path / "results" / "RUN_A" / "summary.json").write_text(
        json.dumps({"server_name": "A", "started_at": "2026-01-01T00:00:00+00:00",
                    "config_fingerprint": "abc", "models": [], "warnings": []}),
        encoding="utf-8",
    )
    (tmp_path / "benchmark.yaml").write_text(
        "project:\n  name: Test\nbenchmark:\n  repetitions: 5\n"
        "  flash_attention: auto\n# ein Kommentar\nmodels: []\n",
        encoding="utf-8",
    )
    srv.state.root = tmp_path
    srv.state.config_name = "benchmark.yaml"
    srv.state.token = None
    srv.state.allow_remote = False
    return TestClient(srv.app)


CROSS_SITE = {"sec-fetch-site": "cross-site", "sec-fetch-dest": "empty",
              "origin": "https://boese.example"}
IMAGE_TAG = {"sec-fetch-site": "cross-site", "sec-fetch-dest": "image"}


def test_foreign_page_cannot_start_a_benchmark(client):
    """Der Kern der Luecke: /api/actions/run war per GET ohne jede Pruefung
    erreichbar und startet Subprozesse."""
    r = client.get("/api/actions/run", headers=CROSS_SITE)
    assert r.status_code == 403


def test_image_tag_cannot_trigger_actions(client):
    assert client.get("/api/actions/run", headers=IMAGE_TAG).status_code == 403


def test_foreign_page_cannot_overwrite_the_config(client):
    r = client.post("/api/config", json={"raw": "models: []\n"}, headers=CROSS_SITE)
    assert r.status_code == 403
    assert "ein Kommentar" in srv.state.config_path.read_text(encoding="utf-8")


def test_same_origin_requests_pass(client):
    r = client.get("/api/runs", headers={"sec-fetch-site": "same-origin", "sec-fetch-dest": "empty"})
    assert r.status_code == 200
    assert r.json()["runs"][0]["id"] == "RUN_A"


def test_unknown_action_is_rejected(client):
    r = client.get("/api/actions/rm", headers={"sec-fetch-site": "same-origin"})
    assert r.status_code == 400


def test_path_traversal_is_blocked(client):
    r = client.get("/api/runs/..%2f..%2fetc", headers={"sec-fetch-site": "same-origin"})
    assert r.status_code in (400, 404)
    r = client.get("/api/runs/../../secret", headers={"sec-fetch-site": "same-origin"})
    assert r.status_code in (400, 404)


def test_raw_config_is_not_empty(client):
    """yaml.safe_load(f) hat das Dateihandle geleert, danach war f.read() == ''."""
    r = client.get("/api/config", headers={"sec-fetch-site": "same-origin"})
    assert r.status_code == 200
    body = r.json()
    assert body["raw"].strip() != ""
    assert "ein Kommentar" in body["raw"]
    assert body["config"]["benchmark"]["repetitions"] == 5


def test_empty_config_is_refused(client):
    r = client.post("/api/config", json={"raw": "   "}, headers={"sec-fetch-site": "same-origin"})
    assert r.status_code == 400
    assert "ein Kommentar" in srv.state.config_path.read_text(encoding="utf-8")


def test_boolean_flash_attention_is_normalized_on_save(client):
    """Sonst entsteht spaeter das ungueltige Argument '-fa False'."""
    payload = {"config": {"project": {"name": "Test"},
                          "benchmark": {"repetitions": 5, "flash_attention": False},
                          "models": []}}
    r = client.post("/api/config", json=payload, headers={"sec-fetch-site": "same-origin"})
    assert r.status_code == 200
    saved = yaml.safe_load(srv.state.config_path.read_text(encoding="utf-8"))
    assert saved["benchmark"]["flash_attention"] == "off"


def test_saving_creates_a_backup(client):
    payload = {"config": {"project": {"name": "Neu"}, "benchmark": {"repetitions": 3}, "models": []}}
    client.post("/api/config", json=payload, headers={"sec-fetch-site": "same-origin"})
    backup = srv.state.config_path.with_suffix(".yaml.bak")
    assert backup.exists()
    assert "ein Kommentar" in backup.read_text(encoding="utf-8")


def test_invalid_config_is_refused(client):
    payload = {"config": {"benchmark": {"repetitions": 0}, "models": []}}
    r = client.post("/api/config", json=payload, headers={"sec-fetch-site": "same-origin"})
    assert r.status_code == 400


def test_token_is_enforced_when_set(client):
    srv.state.token = "geheim"
    assert client.get("/api/runs", headers={"sec-fetch-site": "same-origin"}).status_code == 401
    ok = client.get("/api/runs", headers={"sec-fetch-site": "same-origin",
                                          "x-llmbench-token": "geheim"})
    assert ok.status_code == 200
    srv.state.token = None
