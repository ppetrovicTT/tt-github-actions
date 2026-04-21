# ai_run_summary

Downloads per-job AI summaries and aggregates into a run-level report.

## Usage

```yaml
ai-run-summary:
  needs: your-matrix-job
  if: always()
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - id: summary
      uses: tenstorrent/tt-github-actions/.github/actions/ai_run_summary@main
      with:
        config-path: .github/ai-summary/my-workflow.yaml
        api-key: ${{ secrets.TT_CHAT_API_KEY }}
        api-url: ${{ secrets.TT_CHAT_URL }}
        # slack-bot-token / slack-channel-id: optional, omit to skip Slack
```

## Outputs

| Name | Description |
|------|-------------|
| `report-file` | Path to the aggregated `.md` report |
