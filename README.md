# RAG Loop

A small, local-first pilot for bounded RAG repair loops. The public repository contains generic control code and synthetic tests only.

## Current status

This is a bootstrap scaffold. Synthetic checks demonstrate state handling, evaluation coverage validation, retry limits and a stop before human approval. They do **not** prove that a real RAG answer improved.

Live Codex execution, Claude review, project-specific evaluation, GitHub approval verification and deployment are not enabled by this scaffold. Those adapters must pass a local smoke test before the pilot is armed.

## Local demonstration

Python 3.11 or later; no third-party Python packages are required.

```powershell
python -m unittest discover -s tests -v
python loop_core.py demo --output .local/demo
```

Repeat the demo command to inspect restart behavior. Runtime state and evidence must stay under ignored directories or outside this repository.

## Windows readiness check

Run this from PowerShell; choose a new output filename on every run:

```powershell
.\scripts\preflight.ps1 -OutputPath .local/readiness-001.json -ProjectPath 'C:\path\to\isolated-project'
```

The check records installed commands and authentication status without copying credential files or printing account identifiers. `READY_FOR_SMOKE_TEST` is not release approval. The actual runner account still needs a verified model call, access to the RAG services and an isolated candidate index.

## Pilot policy

- One writer, at most three repair attempts.
- Freeze code, data, index and evaluation versions before collecting a baseline.
- Check complete case coverage, then factual evidence, citations and regressions.
- A missing or invalid report blocks progress. An offline test pass does not imply live RAG quality.
- Keep disputed gold answers visible and out of unqualified quality claims.
- Review a stable candidate once. Stop at human approval, bound to the exact candidate and evidence.
- Credentials, source documents, private code, detailed answers and model transcripts remain local.

## GitHub and local execution

Public CI runs only synthetic tests on GitHub-hosted machines. Do not register a personal workstation containing model credentials and business data as a runner for this public repository.

Use a private execution repository or a separately controlled local executor for real work. Publishing these templates does not register a runner, configure reviewers, start a schedule or enable deployment. See [GitHub setup](docs/github-setup.md).
