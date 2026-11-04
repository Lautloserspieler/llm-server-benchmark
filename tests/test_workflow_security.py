"""Statische Regressionstests fuer die GitHub-Actions-Workflows.

Die Tests ersetzen kein actionlint, sondern sichern die Sicherheitsinvarianten,
die bei Workflow-Aenderungen leicht verloren gehen.
"""

import re
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
_USES_RE = re.compile(r"\buses:\s*['\"]?([^'\"\s#]+)")
_SHA_RE = re.compile(r"^[^@]+@[0-9a-f]{40}$")


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _load(name: str) -> dict:
    return yaml.safe_load(_text(name))


def _steps(workflow: dict) -> list[dict]:
    return [
        step
        for job in workflow.get("jobs", {}).values()
        for step in job.get("steps", [])
    ]


def test_all_actions_are_pinned_to_full_commit_sha():
    offenders: list[str] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for match in _USES_RE.finditer(path.read_text(encoding="utf-8")):
            ref = match.group(1)
            if ref.startswith("./"):
                continue
            if not _SHA_RE.match(ref):
                offenders.append(f"{path.name}: {ref}")

    assert offenders == [], f"Nicht auf Commit-SHA gepinnte Actions: {offenders}"


def test_pull_request_target_workflows_never_checkout_or_run_code():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if "pull_request_target" not in text:
            continue
        workflow = yaml.safe_load(text)
        for step in _steps(workflow):
            uses = str(step.get("uses", ""))
            assert not uses.startswith("actions/checkout"), (
                f"{path.name} checkt untrusted PR-Code unter pull_request_target aus"
            )
            assert "run" not in step, (
                f"{path.name} fuehrt unter pull_request_target Shell-Code aus"
            )


def test_release_watch_no_longer_watches_tgi():
    text = _text("backend-release-watch.yml")
    workflow = _load("backend-release-watch.yml")

    for job_name in ("review", "propose"):
        matrix = workflow["jobs"][job_name]["strategy"]["matrix"]["backend"]
        assert matrix == ["llama_cpp", "vllm"]
    assert "tgi)" not in text


def test_wiki_workflow_does_not_embed_token_in_remote_url():
    text = _text("wiki.yml")

    assert "x-access-token:${GH_TOKEN}@" not in text
    assert not re.search(r"https://[^/\s]+:[^/\s]+@", text)
    assert "GIT_ASKPASS" in text
    assert "GIT_TERMINAL_PROMPT=0" in text
    assert "persist-credentials: false" in text
    assert "git push origin HEAD:master" in text


def test_scorecard_permissions_are_minimal_and_documented():
    workflow = _load("scorecard.yml")

    assert workflow.get("permissions") == {}
    assert workflow["jobs"]["scorecard"]["permissions"] == {
        "security-events": "write",
        "id-token": "write",
        "contents": "read",
        "actions": "read",
    }


def test_ollama_release_watch_splits_read_and_write_jobs():
    workflow = _load("ollama-release-watch.yml")

    assert workflow.get("permissions") == {}
    assert workflow["jobs"]["review"]["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
    }
    assert workflow["jobs"]["propose"]["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
    }
    assert "concurrency" in workflow
    for job_name in ("review", "propose"):
        assert "timeout-minutes" in workflow["jobs"][job_name]

    propose_text = yaml.safe_dump(workflow["jobs"]["propose"], sort_keys=False)
    assert "gh pr create --draft" in propose_text
    assert "git push origin" in propose_text
    assert "gh auth setup-git" in propose_text


def test_all_checkout_steps_disable_persisted_credentials():
    offenders: list[str] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for step in _steps(workflow):
            if not str(step.get("uses", "")).startswith("actions/checkout@"):
                continue
            if step.get("with", {}).get("persist-credentials") is not False:
                offenders.append(path.name)

    assert offenders == [], f"Checkout speichert Credentials: {offenders}"


def test_write_jobs_use_gh_auth_setup_git_instead_of_persisted_checkout_credentials():
    for name in ("backend-release-watch.yml", "ollama-release-watch.yml"):
        propose = yaml.safe_dump(_load(name)["jobs"]["propose"], sort_keys=False)
        assert "gh auth setup-git" in propose


def test_codeql_actions_use_pinned_v4():
    """CodeQL Action v3 is deprecated in December 2026."""
    expected = "1fc58d04a4d4374f921bdac573c3811c240f9c26"
    occurrences = 0
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = _load(path.name)
        for step in _steps(workflow):
            action = str(step.get("uses", ""))
            if action.startswith("github/codeql-action/"):
                occurrences += 1
                assert action.endswith("@" + expected), (
                    f"{path.name}: CodeQL Action must use pinned v4.39.2, got {action}"
                )
    assert occurrences == 5
