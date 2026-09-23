# Security Policy

## Supported versions

Security fixes are applied to the current `main` branch and the latest released version.

## Reporting a vulnerability

Please do **not** open a public GitHub issue for a suspected security vulnerability.

Use GitHub's **Private vulnerability reporting** feature in the repository Security tab whenever available. Include:

- affected version or commit,
- reproduction steps,
- expected and observed behavior,
- potential impact,
- logs or proof-of-concept details with secrets removed.

Please avoid publishing exploit details until a fix or mitigation is available.

## Scope

Relevant reports include, among other things:

- command or argument injection,
- unsafe archive/file handling,
- credential or token exposure,
- insecure downloads or update paths,
- unsafe Docker/container behavior,
- dependency vulnerabilities with a practical impact on llmbench,
- report generation or parsing issues that allow unintended code execution.

General bugs and feature requests should continue to use the normal issue templates.
