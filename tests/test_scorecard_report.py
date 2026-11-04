"""Tests for the human-readable Scorecard SARIF report."""

from scripts.scorecard_report import summary


def test_scorecard_summary_distinguishes_governance_from_vulnerabilities():
    sarif = {
        "runs": [{
            "tool": {"driver": {"rules": [
                {"id": "CodeReviewID", "name": "Code-Review"},
                {"id": "MaintainedID", "name": "Maintained"},
            ]}},
            "results": [
                {
                    "ruleId": "CodeReviewID",
                    "message": {"text": "score is 0: Found 0/28 approved changesets -- score normalized to 0\nClick Remediation section below to solve this issue"},
                    "locations": [{"physicalLocation": {
                        "artifactLocation": {"uri": "no file associated with this alert"},
                        "region": {"startLine": 1},
                    }}],
                },
                {
                    "ruleId": "MaintainedID",
                    "message": {"text": "score is 0: project was created within the last 90 days."},
                },
            ],
        }],
    }
    report = summary(sarif)
    assert "0/28 approved changesets" in report
    assert "unter 90 Tagen" in report
    assert "keine nachgewiesene Code-Schwachstelle" in report
    assert "Repositoryweit (keine Datei)" in report
    assert "nicht automatisch als behoben markieren" in report
    assert "Click Remediation" not in report


def test_scorecard_summary_groups_and_limits_findings():
    sarif = {
        "runs": [{
            "tool": {"driver": {"rules": [{"id": "PinnedDependenciesID", "name": "Pinned-Dependencies"}]}},
            "results": [
                {
                    "ruleId": "PinnedDependenciesID",
                    "message": {"text": "pipCommand not pinned by hash"},
                    "locations": [{"physicalLocation": {
                        "artifactLocation": {"uri": "setup.sh"},
                        "region": {"startLine": i},
                    }}],
                }
                for i in range(1, 16)
            ],
        }],
    }
    report = summary(sarif)
    assert "15 Befunde" in report
    assert "setup.sh:1" in report
    assert "setup.sh:12" in report
    assert "3 weitere Befunde" in report
    assert "setup.sh:13" not in report


def test_scorecard_summary_handles_empty_result():
    assert "Keine Scorecard-Befunde" in summary({"runs": []})
