# Sicherheits-Hardening (v1.7.0)

English: [SECURITY_HARDENING.md](SECURITY_HARDENING.md)

Diese Seite dokumentiert die Sicherheitsmaßnahmen, die im Repository liegen, sowie die Schritte,
die in den GitHub-Repository-Einstellungen manuell gesetzt werden müssen. Sie ist die Referenz für
die Hardening-Arbeit in v1.7.0.

## Im Repository erzwungene Maßnahmen

- **Archivextraktion:** `llmbench/archive.py` validiert jeden TAR-/ZIP-Eintrag vor dem Schreiben.
  Absolute Pfade, `..`, Backslashes, unsichere Symlinks, Hardlinks, Spezialdateien, übergroße Archive und
  zu viele Einträge werden abgelehnt. Die Extraktion nutzt ein Staging-Verzeichnis und ersetzt das
  Installationsverzeichnis erst nach erfolgreicher Prüfung. TAR erlaubt geprüfte relative Symlinks innerhalb des Ziels; ZIP lehnt Symlinks ab.
- **Umgang mit Secrets:** `llmbench/utils.py` redigiert Zugangsdaten in JSON-Dateien, Kommando-Logs,
  Fehlermeldungen und exportierten Logs. Konfigurationsdateien, die einen API-Key enthalten können,
  werden atomar und auf POSIX mit ausschließlichen Eigentümerrechten geschrieben.
- **Workflow-Rechte:** Die Release-Watch-Workflows nutzen schreibgeschützte Review-Jobs und
  Schreibrechte nur in den eigentlichen Proposal-Jobs. Es werden Draft-PRs erstellt, aber nichts
  automatisch gemergt.
- **Action-Pinning:** Jede externe Action ist auf einen vollständigen 40-stelligen Commit-SHA
  gepinnt. Dependabot schlägt weiterhin Updates für GitHub Actions, pip und Docker vor.
- **Image-Pinning:** CUDA-Basisimages und Backend-Images sind auf Version und `sha256`-Digest
  gepinnt. `tests/test_supply_chain.py` sichert das ab.

## Erforderliche GitHub-Einstellungen (manuell)

Diese Einstellungen lassen sich nicht durch Dateien im Repository erzwingen:

1. `main` über ein Ruleset bzw. Branch Protection schützen:
   - Pull Request vor dem Merge verpflichtend,
   - mindestens eine Freigabe und Review durch den Code Owner,
   - veraltete Freigaben nach neuen Commits verwerfen,
   - die Status-Checks aus `tests.yml`, `security.yml` und `docker-image.yml` verpflichtend,
   - Force-Pushes und Branch-Löschung blockieren.
2. Dem Release-Watch-Bot weiterhin das Erstellen von Branches und Draft-PRs erlauben, aber keine
   Merge- oder Ruleset-Umgehungsrechte geben. Auto-Merge für `bot/*`-Branches bleibt deaktiviert.
3. „Allow GitHub Actions to create and approve pull requests“ nur aktivieren, wenn der Release
   Watch es tatsächlich benötigt; der Bot nutzt das Workflow-Token und genehmigt seine eigenen PRs
   nicht.

## Umgang mit Meldungen

- CodeQL-Meldungen mit `high`/`critical` und reproduzierbarem Pfad sind Release-Blocker.
- Medium-Meldungen dürfen behoben oder als akzeptiertes Risiko dokumentiert werden; die Begründung
  gehört in den Pull Request oder in dieses Dokument.
- Ein Code-Scanning-Alert wird erst geschlossen, wenn der Fix gemergt oder die Begründung für einen
  False Positive dokumentiert ist.
- CodeQL und OpenSSF Scorecard nach Änderungen an `.github/workflows/**`, `Dockerfile`,
  `pyproject.toml`, Abhängigkeitsdateien oder `SECURITY.md` erneut ausführen.

## Image- und Installer-Updates

Einen neuen Manifest-Digest ermitteln mit:

```bash
docker buildx imagetools inspect <image>:<tag> --format '{{json .Manifest.Digest}}'
```

Tag und Digest gemeinsam in `Dockerfile`, `compose.yaml`, `compose.build.yaml`, `llmbench/config.py` und
`llmbench/backend_setup.py` aktualisieren. Der Draft-PR des Release Watch entfernt den alten Digest
bewusst; vor dem Merge muss der neue Digest ergänzt werden.

Für Installer gilt:

- Python-Downloads bleiben SHA-256-geprüft.
- `Invoke-UiDownload` wiederholt fehlgeschlagene Downloads, schreibt `.part`-Dateien, begrenzt die
  Größe und prüft optional einen SHA-256-Wert.
- `Assert-LlamaZipSafe` lehnt ZIP-Einträge ab, die das Extraktionsverzeichnis verlassen würden.
- Die Authenticode-Prüfung für Visual Studio Build Tools, CUDA und Docker Desktop ist eine
  Folgeaufgabe; bis dahin verlassen sich diese Installer auf HTTPS und die Hersteller-Endpunkte.

## Folgeaufgaben nach Audit-ID

| ID | Stand in v1.7.0 | Nächster Schritt |
| --- | --- | --- |
| SEC-06 | Dokumentiert | Das oben beschriebene Ruleset in den GitHub-Einstellungen anwenden. |
| SEC-07 | Dokumentiert | `CODEOWNERS` und den Wartungsprozess aktuell halten. |
| SEC-11 | Teilweise umgesetzt | CodeQL deckt Python und Actions mit `security-extended` ab; deterministische Archivtests sind vorhanden. Hypothesis-/Atheris-Ziele für Archiv- und Konfigurationsparser als separate Änderung ergänzen. |
| SEC-12 | Umgesetzt | `SECURITY.md` und `SECURITY.de.md` beschreiben Meldung und Geltungsbereich. |
| SEC-13 | Geprüft | Bewusst breite Exception-Handler bleiben dokumentiert; keine pauschale Entfernung. Vor Releases `ruff` und CodeQL ausführen. |

## Lokale Verifikation

```bash
ruff check llmbench tests scripts
python -m compileall -q llmbench
python -m pytest -q
actionlint .github/workflows/*.yml   # falls actionlint installiert ist
```

Manuelle Prüfungen mit echter Hardware bzw. auf einem GitHub-Runner:

- `workflow_dispatch` für beide Release-Watches: Review-Job ist schreibgeschützt, Proposal-Job
  erstellt einen Draft-PR.
- `workflow_dispatch` für den Wiki-Workflow: Veröffentlichung funktioniert, ohne dass das Token in
  der Remote-URL oder in Logs erscheint.
- Saubere Fedora-Installation, Windows-Installationspfad, NVIDIA-GPU-Start und der
  8-Stunden-Dauertest (Issue #124).
