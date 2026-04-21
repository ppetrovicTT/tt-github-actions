# ai_job_summary

Analyzes CI job logs with an LLM and produces a structured summary (`.md` + `.json`).

## Usage

```yaml
- uses: tenstorrent/tt-github-actions/.github/actions/ai_job_summary@main
  if: always() && !cancelled()
  continue-on-error: true
  with:
    config-path: .github/ai-summary/my-workflow.yaml
    api-key: ${{ secrets.TT_CHAT_API_KEY }}
    api-url: ${{ secrets.TT_CHAT_URL }}
    job-name: ${{ matrix.test-group.name }}  # optional
```

## Consumer config YAML

```yaml
job_summary:
  log_dirs: [output]          # dirs with .log files, relative to $GITHUB_WORKSPACE
  output_dir: output/ai_summaries
run_summary:
  summary_dir: ai_job_summaries
  output_dir: ai_run_summaries
# Optional: extend the bundled analysis config
# analysis_config: .github/ai-summary/my-overrides.yaml
```

## Outputs

| Name | Description |
|------|-------------|
| `summary-dir` | Directory containing `ai_job_summary_<job-id>.md` and `.json` |
