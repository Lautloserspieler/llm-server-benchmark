# Lokaler Community-Export

English: [community-export.md](community-export.md)

`community-export` erzeugt pro vorhandener Suite-Zusammenfassung eine prüfbare
JSON-Datei. Der Vorgang bleibt lokal: kein Upload, keine Anmeldung, keine
Server-Verbindung und kein Ersatz für das private ZIP aus `llmbench export`.

```sh
llmbench community-settings --nickname bench-user
llmbench community-export results/run --out community-exports
llmbench community-export results/run --preview
llmbench community-validate community-exports/community-run-0001.json
```

## Eingaben, Dateien und Rueckgabecodes

Explizite Run-Ordner oder Summary-Dateien werden verarbeitet, ohne rekursive
Suche. `summary.json` hat Vorrang; nur wenn sie fehlt, wird
`summary.partial.json` verwendet. Eine beschaedigte finale Datei ist ein Fehler,
auch wenn eine partielle Datei existiert. Die native Ergebnispruefung erfolgt
vor der Allowlist-Projektion. Unbekannte Felder werden ausgelassen; fehlerhafte
freigegebene Werte erzeugen sichere Feldfehler.

```sh
llmbench community-export results/run-a results/run-b --out public-results --non-interactive
llmbench community-export old-summary.json --model-label '1=Historisches Modell' --preview
llmbench community-export results/run --model-identity 1=fingerprint --preview
llmbench community-export results/run --rehash-models --out public-results
llmbench community-validate --schema
```

Pro Run entsteht `community-run-0001.json`, `community-run-0002.json` usw.
Vorhandene Dateien werden nie ueberschrieben. Standardziel ist
`community-exports`. `--preview` und `--out` sind unvereinbar. Die Vorschau
zeigt exakt dieselben UTF-8-Bytes wie die Datei: sortierte Schluessel, kompaktes
JSON und ein abschliessender Zeilenumbruch. Batch-Vorschau ist ein JSON-Dokument
pro Zeile. Rueckfragen, sichere Fehler und Summen stehen auf stderr; stdout
enthaelt nur Vorschau-JSON. Originalergebnisse werden nie geaendert.
Rueckgabecodes: 0 alle Runs erfolgreich; 1 mindestens ein Run fehlgeschlagen,
gueltige Runs bleiben erhalten; 2 ungueltige Optionen/Einstellungen.

## Spitzname und Modellidentitaet

`community-settings --nickname NAME`, `--clear-nickname` und `--show` verwalten
ausschliesslich den optionalen oeffentlichen Spitznamen. `--settings-file FILE`
ueberschreibt den Pfad fuer Einstellungen und Export. Standardpfade liegen unter
macOS `Library/Application Support/llmbench`, Windows `LOCALAPPDATA/llmbench`
und Linux `XDG_CONFIG_HOME/llmbench` beziehungsweise `.config/llmbench`.
Beschaedigte Einstellungen sind ein Fehler. Export/Vorschau speichern weder
Einstellungen noch Caches. Prioritaet: `--no-nickname`, expliziter `--nickname`,
gespeicherter Spitzname, kein Spitzname. Nach Trimmen sind 1–64 Zeichen erlaubt;
Steuerzeichen und Pfadtrenner sind verboten. Dies ist eine Selbstauskunft, keine
authentifizierte Kontoinhaberschaft. Der Betriebssystembenutzer wird nie ermittelt.

Ein interaktives TTY bietet fuer ungeklaerte lokale Modelle einen freizugebenden
Dateinamen ohne Pfad, einen eigenen Namen oder den Fingerprint. Ohne TTY oder
mit `--non-interactive` gilt ein gueltiger gespeicherter Einzeldatei-Fingerprint
als Standard. Andernfalls ist ein freigegebener Name oder explizites aktuelles
Hashing erforderlich. Modellnamen sind auf 128 Zeichen begrenzt; Steuerzeichen,
Pfade und URLs sind verboten. `--model-label N=TEXT` und
`--model-identity N=fingerprint` verwenden 1-basierte Modellpositionen ueber
die lesbaren Eingaben in ihrer Reihenfolge. Diese Positionen werden nicht
exportiert. Doppelte, widerspruechliche oder ungueltige Positionen sind Fehler.
Fingerprint-Auswahl liest keine Modelldatei: nur `--rehash-models` erlaubt dies.
Entscheidungen werden nach nachgewiesenem Inhaltshash wiederverwendet, auch bei
expliziter Auswahl in einem spaeteren Run. Gleiche Namen beweisen keine Identitaet.
Ein gleicher aufgeloester Pfad darf nur einen freigegebenen Anzeigenamen teilen.

Gespeicherte Einzeldatei-SHA-256 verwendet `recorded_single_file_content`.
Explizites Neuhashing bestaetigt diese Identitaet nur bei gleichem gespeichertem
Hash; andernfalls heisst der Bereich `current_artifact_unverified`, die
historische Identitaet bleibt unbestaetigt. Geteilte GGUFs verwenden
`sha256-shards-v1`: Domain-Trenner, Anzahl, geordnete Inhaltslaengen und
SHA-256-Inhaltsdigests. Der vollstaendige GGUF-Satz ist erforderlich; Dateinamen
gehen nicht in den Digest ein. Historische namensabhaengige Split-Hashes werden
nie als reine Inhaltshashes ausgegeben. Fehlende Dateien sind mit freigegebenem
Namen und nicht verfuegbarem Fingerprint exportierbar. Oeffentliche Registry-ID
und Revision werden nur aus strukturierten gespeicherten Angaben uebernommen.

## Feldvertrag Version 1

Alle Objekte sind geschlossen. Das mitgelieferte Draft-2020-12-Schema beschreibt
Typen; die lokale Pruefung kontrolliert zusaetzlich Provenienz, Zaehler, Zeitfolge,
Kontextkurven, Referenzen, Auslassungen und Konfigurationsfingerprint.
Ergebnisschema 1–3 und Exportschema 1 sind getrennte Versionen. Zukuenftige
Exportversionen, Zusatzfelder, doppelte JSON-Schluessel, NaN/Infinity, boolesche
Zaehler und falsche Einheiten/Quellen/Zustaende werden abgelehnt. Fehler nennen
nur Katalogfeldpfade, numerische Indizes und Codes, niemals Rohwerte,
unbekannte Schluesselnamen, Backend-Ausnahmen oder Validierungs-Tracebacks.

| Quelle | Oeffentliche Darstellung und Herkunft |
|---|---|
| `started_at`, `finished_at`, Abschluss/Ziel | Originalzeit in UTC mit `Z`; recorded/partial/unknown; keine Exportzeit oder erfundene Zeitzone |
| `backend`, `tools`, Messzeilen | Backend-Familie; getrennte Runtime-/Version-Umschlaege und Messtool-Commit/Build/Binaerdigest; Containerdigest ohne private Registry/Tags |
| `models[].model` | Generierte Modell-ID, freigegebener Name, oeffentliche Referenz/Inhaltsfingerprint, Groesse/Shard-Anzahl, explizit unbestaetigte/nicht verfuegbare Identitaet |
| Benchmark-/Profil-/Endpoint-/Soak-Konfiguration | Typisierte konfigurierte Werte, getrennt vom effektiven Runtime-Zustand; SHA-256 ueber Backend und alle behaltenen Einstellungen, Bereich `exported_configuration_v1`, Vollstaendigkeit `retained_configured_fields` |
| `profiles[].benchmarks` | Alle freigegebenen Prompt-/Generation-/Langkontextzeilen, Reihenfolge/Wiederholungszahl, numerisch abgeleiteter Testname, tokens/s und strukturierter Ausgang/Fehlercode |
| `profiles[].context_capability` | Angeforderte/abgeschlossene Tiefen, vollstaendige pass/OOM/timeout/partial-Kurve, echtes verifiziertes Maximum und erste Fehlergrenze; keine erfundene TTFT/TPOT |
| `profiles[].kv_cache` | Typisierte gemeinsame Cachefelder und geschlossener nativer llama.cpp/vLLM-Katalog, urspruengliche value/source/unit/status und freigegebene Evidenz |
| `models[].endpoint`, `models[].soak` | Modellbezogene Endpoint-Zaehler/Parallelitaet/Latenzen in Sekunden, Warmup/Einstellungen; CPU-/GPU-Soak-Dauer, Last, Durchsatzabfall/Drosselung und aufgeloeste Profilreferenzen |
| `hardware` | CPU-/GPU-Produktfakten, Kern-/Speicher-/Kapazitaets-/Treiberwerte, OS-Familie und gespeicherte unterstuetzte Version/Architektur; generierte Geraete/Domaenen und Bandbreitenumschlaege; bekannte NVIDIA-MiB werden Bytes |
| Urspruengliche Workload-/Modell-/Run-Telemetrie | Freigegebene Auslastungs-/Takt-/Temperatur-/Speicheraggregate, CPU-/GPU-Energie und Komponenten-/Wandstrom-Umschlaege, Quelle/Abdeckung, tokens/J, J/1k tokens, Wh/1k tokens und umgesetzte Referenzen |
| Freigegebene Evidenz | Katalogisierte Methode/Provider/Phase/Bereich/Abdeckung und typisierte Algorithmuseingaben; freie Gruende werden `unknown_reason`; Referenzen/beliebige Metadaten entfallen |

V3 behaelt tatsaechliche Herkunft, einschliesslich gemessener versus berechneter
Energie. Historische Referenzwerte behalten ihre Zahl mit null-Quelle,
`unknown` und `legacy_provenance_missing`; es entsteht keine nachtraegliche
Messherkunft. Null-Werte fuer `value` und `source` bleiben explizit. Partielle,
kapazitaetsbegrenzte, fehlgeschlagene, uebersprungene und Timeout-Ausgaenge bleiben
erhalten. Run-Abschluss bedeutet nicht, dass jeder Workload bestand. Mindestdaten
sind Modellidentitaet und Messung oder strukturierter Fehler; leere Runs sind ungueltig.

Automatische Benutzernamen, Hostnamen, Pfade/Shard-Namen, Netzwerkadressen,
Zugangsdaten/Umgebung, Prozesse/PIDs/Befehle, Prompts/Antworten/Request-Details,
Logs/Ausnahmetexte, Seriennummern/UUIDs/PCI, Disk-/Execution-/Power-Scheme-Daten
und beliebige Zukunftsfelder werden ausgelassen und nicht zu Hash-Identifikatoren
verarbeitet. Freigegebene Produkt-/Modell-/Konfigurationsdaten koennen weiterhin
identifizierend sein; Anonymitaet wird nicht versprochen. `foreign_gpu_load_detected`
und strukturiertes `baseline_busy` erhalten Qualitaetssignale ohne Prozessidentitaeten.

## Gruppen und Beispiele

Standardmaessig sind alle freigegebenen Gruppen enthalten. `--exclude` akzeptiert
`hardware`, `energy`, `capabilities`, `telemetry`, komma-getrennt und einmalig in
`omitted_groups`. Hardware verbirgt statische Fakten; verbleibende Beobachtungen
behalten minimale nicht identifizierende Domaenenreferenzen. Energy entfernt
Strom/Energie/Effizienz in jedem Bereich. Telemetry entfernt Auslastung, Temperatur,
Takt und Speicheraggregate; separat ausgewaehlte Energie/Effizienz/Bandbreite bleibt.
Capabilities entfernt KV-/Kontextfaehigkeit und Bandbreite; Kernmesszeilen und
Kontexttiefen bleiben. Fehlend, null, null Messwert und Auslassung sind verschieden;
Referenzen bleiben konsistent.

Generierte Beispiele unter [examples/community](examples/community/) sind
`happy.llama_cpp.json`, `happy.vllm.json`, `partial.json`, `legacy.json` und
`redacted.json`. Sie stammen aus nativ kodierten Suite-Fixtures, werden lokal
geprueft und sind keine echten Maschinen-Benchmarkaussagen. Export/Pruefung starten
kein Backend, ermitteln keine Hardware, laden nichts herunter, authentifizieren
nicht und kontaktieren kein Netzwerk. Submission/Visualisierung sowie Multi-Turn-
Gespraechsbenchmarks benoetigen eine separate Planung und Freigabe.

Die Vorschau schreibt exakt das spätere JSON nach stdout und erzeugt keine
Datei. Hardware, Energie, Fähigkeiten und Telemetrie sind standardmäßig
enthalten und können gezielt ausgelassen werden. Ein Nickname ist optional,
lokal und eine Selbstauskunft; ein Betriebssystem-Benutzername wird nie gelesen.

Akzeptiert werden nur Suite-`summary.json`- und `summary.partial.json`-Dateien
der Ergebnis-Schemas 1–3, keine eigenständigen Stress-JSON-Dateien.
