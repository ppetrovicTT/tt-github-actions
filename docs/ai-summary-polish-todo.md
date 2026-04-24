# AI Summary — Polish To-Do

Bugs and improvements identified while iterating on the shield runner
integration. To address after the matrix + CI integration is green.

## Root theme

The tool currently classifies jobs **based only on log contents**. It has no
awareness of the GHA job/run status. This produces several wrong classifications:

| Tool sees | GHA reality | Tool says | Should say |
|---|---|---|---|
| Missing summary | Job never dispatched (infra) | INFRA_FAILURE | INFRA_FAILURE ✓ |
| Missing summary | Job cancelled | INFRA_FAILURE | CANCELLED |
| Log has no signals | Job succeeded | SUCCESS | SUCCESS ✓ |
| Log has no signals | Job failed pre-benchmark | SUCCESS | UNKNOWN / CRASHED |

Fix direction: the tool needs GHA context. Either the caller passes
`job.status` / `needs.*.result`, or ai-summary queries the GH API to resolve
each expected job's conclusion.

## Pending

0. **Improve vLLM server-startup error patterns in `analysis.yaml`.**
   Now that the GHA-context fix handles the "job failed + no signals" case as
   UNKNOWN, we should still add better patterns so these failures classify
   accurately (CRASHED with a root cause) rather than bucket into UNKNOWN.
   Patterns for: `ModuleNotFoundError`, `ImportError`, pydantic
   `ValidationError`, vLLM `Error in loading model architecture`, AttributeError
   during `from_pretrained`.

1. **False SUCCESS when a GHA job fails pre-benchmark.**
   Example: vLLM server fails to start with a ModuleNotFoundError. The server
   log contains a stack trace that doesn't match any category pattern, there's
   no pytest output, no `TT_FATAL`, no timeout keyword. The tool reports
   SUCCESS. See run 24881237182 `[N150] Qwen2.5-VL-3B-Instruct` job for an
   example.

2. **Cancelled jobs get stubbed as INFRA_FAILURE.**
   When a run is cancelled mid-flight, legs that never produced an
   `ai_job_summary_*` artifact get synthesised as INFRA_FAILURE with reason
   "Runner failed to start — no summary received". Cancelled ≠ infra failure.
   Introduce a CANCELLED status and distinguish.
   See run 24884058418 for an example.

3. **Add a CANCELLED status to the model.**
   Covered by (2). Should appear in the per-job summary and the run-level
   table the same way SUCCESS / CRASHED / TESTS_FAILED / INFRA_FAILURE do.

4. **Tool should refuse SUCCESS when the caller job's `job.status` is
   `failure`.**
   Quick partial fix for (1) — add a `job-status` input to `ai_job_summary`
   action. When passed `failure`, override a SUCCESS classification to
   UNKNOWN (or route through the LLM for better reasoning).

5. **Improve vLLM server-startup error patterns in `analysis.yaml`.**
   Patterns for: `ModuleNotFoundError`, `ImportError`, pydantic
   `ValidationError`, vLLM `Error in loading model architecture`, server
   process exit before "Application startup complete". These should land
   as CRASHED.

## Done

- [x] `ai_run_summary` cp-to-/tmp removed; install directly from action cache
  (hatchling build backend means no writes back to source).
  tt-github-actions `932dc0a`.
- [x] `Show report` step surfaced in the caller workflow.
  tt-github-actions `f9f7f96` (keep output_dir), tt-metal `ed87ad4` (add step).
- [x] **GHA context via jobs-list (fixes 1, 2, 3, 4 above).**
  - `ai_job_summary` action gains `job-status` input; CLI gains `--job-status`.
    When GHA says the job failed but the log-based classifier finds no signals,
    tool reports UNKNOWN with `category: unknown:no_log_signals`.
  - `ai_run_summary` action replaces `matrix-manifest` with `jobs-filter`;
    adds a `github-script` step that queries
    `listJobsForWorkflowRun` and writes the JSON to `/tmp/ai-summary/jobs.json`.
    CLI gains `--jobs-list` and `--jobs-filter`.
  - New module `jobs_list.py` (replaces `manifest.py`): drops cancelled legs
    entirely, stubs INFRA_FAILURE for failed legs with no summary, overrides
    SUCCESS -> UNKNOWN when an artifact disagrees with GHA conclusion.
  - Caller workflow (tt-metal `vllm-nightly-tests-impl.yaml`) drops the
    matrix manifest upload, passes `job-status: ${{ job.status }}` to
    `ai_job_summary`, and passes `jobs-filter: "vllm-tests / "` to
    `ai_run_summary`.
