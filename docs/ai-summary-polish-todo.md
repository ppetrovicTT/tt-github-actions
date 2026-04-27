# AI Summary — Polish To-Do

Tracker for bugs and improvements that come up while integrating the tool
into new repos.

## Pending

*(none currently)*

## Done

- [x] **Hatchling build backend** — `ai_run_summary`/`ai_job_summary` install
  directly from the action cache without writing back to source (the prior
  setuptools/egg-info pollution bug is gone).
- [x] **`Show report` step** — surfaced in caller workflows so the run report
  is visible directly in the GHA log without unwrapping a collapsed group.
- [x] **False SUCCESS on pre-benchmark crash** — `has_crash` in
  `extract.py` now recognises anchored Python exceptions
  (`AttributeError`, `KeyError`, `RuntimeError`, `ModuleNotFoundError`,
  `ImportError`). Broader types (`AssertionError`, `ValueError`,
  `TypeError`, `IndexError`) are deliberately excluded — they appear
  routinely in healthy pytest output.
- [x] **Identical tracebacks don't bloat the LLM context** — added
  `_dedupe_error_sections`, normalising timestamps, PIDs (both `pid:` and
  `pid=` forms), hex addresses, line numbers, and the extraction line-prefix.
- [x] **Run-level reconciliation via workflow-native data flow** — replaced
  the prior github-script + env-var smuggle with two action inputs:
  `expected-jobs` (matrix output JSON) and `run-result` (`needs.<>.result`).
  Missing legs surface as `INFRA_FAILURE` with `category: infra:no_artifact`.
  Suppressed when `run-result` is `cancelled` or `skipped`.
- [x] **Dropped `--job-status` safety net** — the Python-exception expansion
  covers the common case; expected-jobs reconciliation covers the rest.
