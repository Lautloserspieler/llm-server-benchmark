#!/usr/bin/env python3
"""Generate a readable, evidence-based GitHub Actions summary from Scorecard SARIF."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

CONTEXT = {
    "Code-Review": (
        "Prozessbewertung, keine nachgewiesene Code-Schwachstelle.",
        "Menschliche PR-Freigaben und verpflichtende Reviews prüfen. "
        "Automatisierte Tests, CodeQL und KI-/Bot-Reviews zählen hier nicht als menschliche Reviews.",
    ),
    "Maintained": (
        "Wartungsbewertung, keine nachgewiesene Code-Schwachstelle.",
        "Bei Repositories unter 90 Tagen ist diese Bewertung altersbedingt. "
        "Nicht durch künstliche Commits oder automatisches Schließen der Warnung umgehen.",
    ),
    "Pinned-Dependencies": (
        "Supply-Chain-Härtung, nicht automatisch eine bekannte verwundbare Abhängigkeit.",
        "Die genannte Zeile und den nicht gepinnten Befehl prüfen; versionierte "
        "Abhängigkeiten, Digests oder Hashes verwenden, wo technisch sinnvoll.",
    ),
    "Fuzzing": (
        "Fehlende Testabdeckung, keine bestätigte Schwachstelle.",
        "Gezieltes Fuzzing für Archivparser, Konfigurations- und Ergebniseingaben erwägen.",
    ),
    "SAST": (
        "Abdeckung statischer Analysen, keine bestätigte Schwachstelle.",
        "Prüfen, ob SAST auf allen relevanten Commits/PRs tatsächlich ausgeführt wird.",
    ),
}

def clean(value: object) -> str:
    """Preserve evidence while preventing Markdown table/HTML formatting issues."""
    return str(value or "").replace("|", r"\|").replace("<", "&lt;").replace(">", "&gt;")

def location(result: dict) -> str:
    locations = result.get("locations") or []
    if not locations:
        return "Repositoryweit"
    physical = locations[0].get("physicalLocation") or {}
    uri = (physical.get("artifactLocation") or {}).get("uri", "")
    if not uri or uri == "no file associated with this alert":
        return "Repositoryweit (keine Datei)"
    line = (physical.get("region") or {}).get("startLine")
    return f"{uri}:{line}" if line else str(uri)

def summary(data: dict) -> str:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for run in data.get("runs", []):
        rules = {
            rule.get("id"): rule
            for rule in (run.get("tool", {}).get("driver", {}).get("rules") or [])
        }
        for finding in run.get("results") or []:
            rule_id = finding.get("ruleId", "Unknown")
            rule = rules.get(rule_id, {})
            name = rule.get("name") or rule_id.removesuffix("ID")
            grouped[name].append(finding)

    lines = [
        "## OpenSSF Scorecard – verständlicher Sicherheitsbericht",
        "",
        f"**Aktuelle SARIF-Befunde:** {sum(map(len, grouped.values()))} "
        f"aus **{len(grouped)} Regeln**.",
        "",
        "> Dieser Bericht beschreibt ausschließlich den **aktuellen Scorecard-Lauf**. "
        "Die Anzahl offener Alerts im GitHub-Security-Tab kann davon abweichen, "
        "weil dort auch ältere Befunde und andere Scanner angezeigt werden. "
        "Ein grüner Workflow bedeutet nicht, dass alle Scorecard-Prüfungen volle Punktzahl haben.",
        "",
    ]

    if not grouped:
        lines.append("Keine Scorecard-Befunde in der SARIF-Datei.")
        return "\n".join(lines) + "\n"

    for name, findings in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        note, action = CONTEXT.get(
            name,
            (
                "Scorecard-Projekt- oder Supply-Chain-Prüfung; Befund individuell bewerten.",
                "Originalmeldung und verknüpfte Scorecard-Regeldokumentation prüfen.",
            ),
        )
        lines.extend([
            f"### {clean(name)} ({len(findings)} Befunde)",
            "",
            f"**Einordnung:** {note}",
            "",
            f"**Nächster Schritt:** {action}",
            "",
            "| Fundort | Originalursache |",
            "| --- | --- |",
        ])
        for finding in findings[:12]:
            message = (finding.get("message") or {}).get("text", "")
            message = re.sub(r"\s*Click Remediation section below to solve this issue\s*", "", message)
            lines.append(
                f"| {clean(location(finding))} | "
                f"{clean(' '.join(message.split()))[:350]} |"
            )
        if len(findings) > 12:
            lines.append(f"| Weitere | {len(findings) - 12} weitere Befunde; Details im SARIF-/Security-Tab |")
        lines.append("")

    lines.extend([
        "### Umgang mit älteren Alerts",
        "",
        "1. Aktuellen SARIF-Befund mit dem offenen GitHub-Alert vergleichen.",
        "2. Falls der Befund noch besteht: Ursache beheben und erneut scannen.",
        "3. Falls er nicht mehr besteht: Scanner-Kategorie, Branch und "
        "SARIF-Fingerprint prüfen; **nicht automatisch als behoben markieren**.",
        "4. Bewusste Restrisiken nur nach dokumentierter Prüfung als akzeptiert einstufen.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sarif", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = summary(json.loads(args.sarif.read_text(encoding="utf-8")))
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
