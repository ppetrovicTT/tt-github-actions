# AI Job Summary Tool

CI log analysis: extract errors → LLM classification → structured markdown summary.

## Architecture

```
cli.py             → orchestrates the flow
extract.py         → log extraction, pattern matching, get_job_status(), apply_llm_status()
summarize.py       → LLM prompt, response parsing, markdown formatting
context.py         → CI context (PR info, code snippets from stack traces)
config.py          → config loading (package defaults + project override)
config_context.py  → CI config extraction from log content (for error attribution)
extract_configs.py → layer-aware config extraction for error attribution
llm_client.py      → LLM API client (TT Chat / OpenAI compatible)
```

## Config

One YAML per project (e.g. `config/tt-shield.yaml`). Defines all project-specific behavior.

```yaml
tool_dir: .github/tools/ai-summary       # required, must have pyproject.toml

log_dirs:                                  # required, all must have .log files
  - path/to/frontend_logs                  # each dir = a required process
  - path/to/server_logs                    # if any missing → INFRA_FAILURE (process never started)

output_dir: path/to/output/ai_summaries    # tool writes .md and .json directly here
model: anthropic/claude-sonnet-4-5-20250929

categories: { ... }                        # failure patterns for LLM classification
layers: [ ... ]                            # stack layers for error attribution
test_patterns: [ ... ]                     # test result extraction
failed_test_patterns: [ ... ]              # individual failed test extraction
repos:
  default_branches: [main, dev]
```

## Tool flow

1. Load config, resolve `log_dirs`
2. **All dirs missing** → INFRA_FAILURE, no LLM, done
3. Extract from present dirs, `get_job_status()`
4. **All dirs present + SUCCESS** → write summary, no LLM, done
5. **Partial dirs + no errors** → INFRA_FAILURE, no LLM, done
6. **Partial dirs + errors found** → call LLM for root cause analysis, status stays INFRA_FAILURE
7. **All dirs present + errors** → call LLM, LLM determines status via `apply_llm_status()`
8. Write `ai_summary_{JOB_ID}.md` and `ai_summary_{JOB_ID}.json` to `output_dir`

The key design: INFRA_FAILURE is determined once from missing dirs and never overridden.
LLM only sets the status when all dirs are present. For partial logs, LLM provides
category/root_cause analysis but the status stays INFRA_FAILURE.

## Action

Wrapped by `.github/actions/ai-job-summary/action.yml`.

**Inputs**: `config-path` (required), `api-key` (required, secret), `api-url` (required)

**Flow**: validate config → detect job metadata (`job.check_run_id`, `job.name` via runner context) → install tool → run CLI → set outputs

**Outputs**: `summary-dir`

**Status values**: `SUCCESS`, `CRASHED`, `TIMEOUT`, `TESTS_FAILED`, `EVALS_BELOW_TARGET`, `INFRA_FAILURE`, `UNKNOWN`, `ERROR`

## Status logic

Status is set exactly once — no triple-override chain.

- `INFRA_FAILURE` — set by CLI when any `log_dir` is missing. Never overridden by LLM.
- `TIMEOUT` — set by `get_job_status()` from extraction. LLM cannot override.
- `CRASHED`, `TESTS_FAILED`, `EVALS_BELOW_TARGET` — LLM may override extraction via `apply_llm_status()`.
- `SUCCESS` — extraction found no errors. LLM is skipped entirely.

`_LLM_STATUS_MAP` maps LLM enums → display JobStatus. TIMEOUT and INFRA_FAILURE are intentionally absent — they are set before LLM is called and never changed.

## JSON output

`_job.name` and `_job.url` always come from CLI args (`--job-name`, `--job-url`), not from log content. This ensures the JSON is usable by downstream tools (ai-run-summary) regardless of whether the log contains job metadata.

## Testing

Fixture-based approach using real-world CI logs:
- `tests/fixtures/log_samples/` — real CI log files covering each failure category
- `tests/fixtures/mock_responses/` — representative LLM JSON responses for each category

Test files:
- `test_extraction.py` — calls `extract_log()` on fixture log files, asserts extraction signals
- `test_status.py` — `get_job_status()` and `apply_llm_status()` unit tests
- `test_summarize.py` — prompt building, LLM response parsing, markdown formatting
- `test_cli.py` — full pipeline: config → log validation → extract → output

When adding a new failure category: add a fixture log + mock response, then add extraction and CLI tests.

## Portability

To add this tool to a new repo:
1. Copy or reference the tool (or publish as GitHub Action)
2. Create a project config YAML defining `tool_dir`, `log_dirs`, categories, etc.
3. Add to workflow:
```yaml
- uses: ./.github/actions/ai-job-summary
  with:
    config-path: path/to/config.yaml
    api-key: ${{ secrets.API_KEY }}
    api-url: ${{ secrets.API_URL }}
```
