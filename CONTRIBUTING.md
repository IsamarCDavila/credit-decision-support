# Contributing

**English** | [Español](CONTRIBUTING.es.md)

## Documentation

English is the primary language. Root-level Markdown uses `.md` for English and `.es.md` for Spanish. English technical documents live in `docs/`; Spanish equivalents mirror their paths under `docs/es/`. Every document has reciprocal language links near its title. Update both editions in the same pull request, including tables, warnings, and validation limits. Keep API identifiers, paths, commands, and state names unchanged across translations.

Write for a reader who has no access to development conversations. Describe the product, architecture, requirements, verified behavior, and known limitations. Exclude assistant instructions, chat history, suggested repository names, account-connection steps, session-specific machine observations, and draft text intended for a pull request. Reusable setup instructions should state prerequisites and expected outcomes.

Distinguish planned behavior, implementation, and measured results. A design contract does not prove a control works. Validation records identify the command, coverage, and limits. Performance claims require reproducible measurements. Reports use the simulation label appropriate to their language: SIMULATION in English and SIMULACIÓN in Spanish.

## Changes and review

Use one branch and pull request per implementation milestone. Describe the concrete change, rationale, validation, and material limitations. Keep pull request titles and commit messages in English; provide an English-first Spanish summary when useful. Merge only after the phase acceptance criteria and applicable checks pass.

## Data handling

Commit only synthetic fixtures. Do not commit `.env` files, credentials, real customer documents, provider logs, or unreviewed generated output. Infrastructure extensions require an architecture decision and evidence that the added dependency solves a measured problem.
