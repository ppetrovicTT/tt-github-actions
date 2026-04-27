# ai_run_summary

Downloads per-job AI summaries (produced by `ai_job_summary`) and aggregates
them into one run-level report. Optionally renders the report as a PNG and
posts it to Slack.

## Usage

```yaml
ai-run-summary:
  needs: [generate-matrix, your-matrix-job]
  if: always()
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4         # required: action reads config from the repo
    - id: summary
      uses: tenstorrent/tt-github-actions/.github/actions/ai_run_summary@main
      with:
        config-path: .github/workflows/<workflow-name>-ai-summary-config.yaml
        api-key: ${{ secrets.TT_CHAT_API_KEY }}
        api-url: ${{ secrets.TT_CHAT_URL }}
        # Pass these two together to surface INFRA_FAILURE rows for matrix
        # legs that produced no summary (runner died, container setup failed):
        expected-jobs: ${{ needs.generate-matrix.outputs.matrix }}
        run-result:    ${{ needs.your-matrix-job.result }}
        # Optional Slack delivery — omit both to skip:
        slack-bot-token: ${{ secrets.SLACK_BOT_TOKEN }}
        slack-channel-id: ${{ secrets.SLACK_CHANNEL_ID }}
```

`expected-jobs` and `run-result` must be passed together (or both omitted);
passing only one is a hard error. When `run-result` is `cancelled` or
`skipped`, no synthesis is performed.

## Outputs

| Name | Description |
|------|-------------|
| `report-file` | Path to the aggregated `.md` report |
