# ai_job_summary

Analyzes CI job logs with an LLM and produces a structured per-job summary
(`.md` + `.json`).

> **Runtime requirement:** this action runs the tool inside the calling job's
> environment without creating its own venv. It MUST be invoked from a job
> running in a Docker container that has an active virtualenv (i.e. `VIRTUAL_ENV`
> is set — typical for the tt-metal/tt-shield Docker images that pre-create
> `/opt/venv`). For bare runners, use `ai_run_summary`'s pattern (it builds
> its own venv) as a model.

## Usage

```yaml
- uses: tenstorrent/tt-github-actions/.github/actions/ai_job_summary@main
  if: always() && !cancelled()
  continue-on-error: true
  with:
    config-path: .github/workflows/<workflow-name>-ai-summary-config.yaml
    api-key: ${{ secrets.TT_CHAT_API_KEY }}
    api-url: ${{ secrets.TT_CHAT_URL }}
    job-name: ${{ matrix.test-group.name }}  # optional; defaults to job.name
```

## Inputs

| Name | Required | Description |
|------|---|-------------|
| `config-path` | yes | Path to the consumer config YAML (see below). Resolved relative to the calling step's working directory. |
| `api-key` | yes | LLM API key (secret). |
| `api-url` | yes | LLM API URL. |
| `job-name` | no | Job name used in the summary header and stamped as `_job.name` in the output JSON. Must match the corresponding entry in `expected-jobs` (passed to `ai_run_summary`) for INFRA_FAILURE reconciliation to work. Defaults to `job.name`. |

## Consumer config YAML

```yaml
job_summary:
  log_dirs: [output]          # dirs with .log files, relative to the caller's pwd
  output_dir: output/ai_summaries
run_summary:
  summary_dir: ai_job_summaries
  output_dir: ai_run_summaries
```

Categories, layers, and analysis patterns come from the bundled
`analysis.yaml` shipped with the tool. The consumer config only specifies
where logs live and where summaries should land.

## Outputs

| Name | Description |
|------|-------------|
| `summary-dir` | Directory containing `ai_job_summary_<job-id>.md` and `.json` |
