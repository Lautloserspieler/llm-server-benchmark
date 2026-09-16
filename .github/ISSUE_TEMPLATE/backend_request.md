---
name: "Backend Request"
about: "Unterstützung für einen neuen Inferencing-Server vorschlagen / Request support for a new inference server"
title: "[Backend] "
labels: ["enhancement", "backend"]
assignees: []
---

<!--
Bitte auf Deutsch oder Englisch ausfüllen — beides ist willkommen.
Please fill this out in German or English — either is fine.

Vor dem Absenden: einen Blick in ROADMAP.md werfen (Backend-Support-Matrix +
"Ideen, keine Zusagen") — vielleicht ist das gewünschte Backend schon geplant
oder bereits in Arbeit.
Before submitting: check ROADMAP.md (backend support matrix + "Ideas, no
commitments") — the backend you want may already be planned or in progress.
-->

## Backend

Name des Servers/Frameworks (z. B. SGLang, TensorRT-LLM, ...):
Name of the server/framework (e.g. SGLang, TensorRT-LLM, ...):

Projekt-Link / Project link:

## API-Stil / API style

- [ ] OpenAI-kompatibel (`/v1/completions` bzw. `/v1/chat/completions`) / OpenAI-compatible
- [ ] Eigene native API / Own native API (bitte Endpunkte nennen / please name the endpoints)
- [ ] Unbekannt / Unknown

## Health-Check

Welcher Endpunkt zeigt an, dass der Server bereit ist (z. B. `/health`)?
Which endpoint indicates the server is ready (e.g. `/health`)?

## Verteilung / Distribution

- [ ] Offizielles Docker-Image verfügbar / Official Docker image available (Name/Tag: ___)
- [ ] Nur natives Binary/pip-Paket / Native binary/pip package only
- [ ] Unbekannt / Unknown

<!-- Neue Backends laufen in llmbench bevorzugt als Docker-Container
     (siehe ROADMAP.md) — ein offizielles Image ist hilfreich, aber keine
     harte Voraussetzung für den Issue selbst. -->
<!-- New backends in llmbench are expected to run as Docker containers
     (see ROADMAP.md) — an official image helps, but is not a hard
     requirement to file this issue. -->

## Warum dieses Backend? / Why this backend?

Was macht diesen Server für Benchmark-Vergleiche relevant?
What makes this server relevant for benchmark comparisons?

## Zusätzlicher Kontext / Additional context

<!-- Dokumentation, bekannte Einschränkungen, eigene Erfahrung mit dem Server, ... -->
<!-- Documentation, known limitations, your own experience with the server, ... -->
