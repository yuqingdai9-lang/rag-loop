# Repository scope

This repository is intended to be safe to publish. Use synthetic inputs in source code, fixtures, demonstrations and CI. Keep project-specific source documents, answers, internal URLs, local paths, credentials and raw model transcripts outside the tracked files.

# Verification boundaries

- Run `python -m unittest discover -s tests -v` after changing the state engine.
- Demonstrations must identify themselves as synthetic and must never mark a live release ready.
- Missing evidence, skipped required checks and malformed reports block progression.
- Repair tasks may propose changes to product code. They must not lower budgets, alter frozen gold answers, waive gates or approve their own output.
- These instructions are guidance. Live execution also requires an independent permission boundary for the verifier and approver.
- This repository does not contain a deployment adapter. Do not interpret a local JSON approval field as authority to deploy.
