# AI Summary — Polish To-Do

Tracker for bugs and improvements surfaced while iterating on the shield-runner
integration.

## Pending

*(none currently — see Done below.)*

## Done

- [x] `ai_run_summary` cp-to-/tmp removed; install directly from action cache
  (hatchling build backend means no writes back to source).
  tt-github-actions `932dc0a`.
- [x] `Show report` step surfaced in the caller workflow.
  tt-github-actions `f9f7f96` (keep output_dir), tt-metal `ed87ad4` (add step).
- [x] **False SUCCESS when a GHA job fails pre-benchmark.**
  `has_crash` in `extract.py` now recognises anchored Python exceptions —
  `AttributeError`, `KeyError`, `RuntimeError`, `ModuleNotFoundError`,
  `ImportError`. When a vLLM server dies on an uncaught exception the tool now
  correctly reports `CRASHED` with LLM-classified root cause, instead of SUCCESS.
  Broader types (`ValueError`, `TypeError`, `IndexError`) are deliberately
  excluded because they appear routinely in healthy pytest output.
- [x] **Identical tracebacks don't bloat the LLM context.**
  Added `_dedupe_error_sections` that collapses repeated sections (identical
  after stripping timestamps, PIDs, hex addresses, line numbers, and the
  extraction line-number prefix). `_normalize_line` now handles `pid=N` /
  `tid=N` in addition to the colon form, matching real vLLM / tt-metal logs.
- [x] **Clean run-level reconciliation via workflow-native data flow.**
  Replaced the github-script `listJobsForWorkflowRun` query (plus the
  `GHA_JOBS` env-var smuggle and the `--jobs-filter` / `jobs_list.py`
  machinery) with two caller inputs:
  - `expected-jobs: ${{ needs.<matrix-job>.outputs.matrix }}` — authoritative
    list of matrix legs.
  - `run-result: ${{ needs.<matrix-job>.result }}` — aggregate success /
    failure / cancelled / skipped.
  Policy: when `run-result` is `cancelled` or `skipped` nothing is synthesised
  (user aborted or matrix didn't run, no expectations to meet). Otherwise
  expected legs with no artifact become `INFRA_FAILURE` stubs with
  `category: infra:no_artifact`.
- [x] **Dropped `--job-status` safety net.**
  The Python-exception expansion covers the common case it existed for. The
  expected-jobs reconciliation covers the rest. Fewer parallel status sources.
