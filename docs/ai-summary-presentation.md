# AI Summary — Presentation Slides

Use `---` as slide separators. Each section below = one slide.

---

## Slide 1 — Title

**AI-Powered CI Summaries**
*Turning 5,000-line log files into one-glance reports*

Pavle Petrovic · Tenstorrent · April 2026

---

## Slide 2 — The Problem

A failing job in our CI could be broken at **any layer of a deep stack**:

```
  Application / benchmark harness
  vLLM serving layer
  Model implementation
  TTNN operations
  TT-Metal (kernels, dispatch, trace)
  UMD / driver
  Hardware / runner infrastructure
```

- Thousands of lines of interleaved logs from every layer at once
- The symptom (a failing pytest) rarely tells you which layer caused it
- A TT-Metal crash looks like a vLLM timeout, which looks like a test failure
- Engineers spend minutes to hours per morning figuring out *where* in the stack to look

**The cost:** wasted engineering time, slow response to real regressions, incident fatigue.

---

## Slide 3 — What We Built

**`ai-summary`** — a two-stage CI analyzer:

1. **`ai-job-summary`** runs per job, reads the logs, classifies the failure
2. **`ai-run-summary`** aggregates all jobs into one run-level report

**Per-job output** — a one-screen summary attached as a build artifact:
```
🔴 CRASHED — [BH-DB] Llama-3.1-8B-Instruct with sampling-tests
Root cause: TT_FATAL in tt_metal/dispatch/command_queue.cpp:227
            dispatch timeout while enqueueing program
Layer:      tt-metal (framework)
Failed tests: 8 tests dependent on crashed dispatch
Suggested:  Reset device; check if regression hit command queue handling
```

**Run-level report** — one table, one row per matrix leg:

| Status | Job | Root cause |
|--------|-----|------------|
| 🟢 | [BH-LB] Llama-3.1-8B | — |
| 🔴 CRASHED | [BH-DB] Llama-3.1-8B | TT_FATAL in dispatch (tt-metal) |
| 🟠 TESTS_FAILED | [WH-T3K] Qwen3-VL-32B | 1 accuracy assertion in test_top_p |
| ⚫ INFRA_FAILURE | [WH-T3K] Gemma3-27B | Runner never started |

Delivered to Slack as a PNG so you can triage from your phone.

---

## Slide 4 — Design: Two-Stage Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│  Matrix job 1        Matrix job 2        Matrix job N       │
│  ┌───────────┐       ┌───────────┐       ┌───────────┐     │
│  │ test run  │       │ test run  │       │ test run  │     │
│  │    ↓      │       │    ↓      │       │    ↓      │     │
│  │ ai-job-   │       │ ai-job-   │       │ ai-job-   │     │
│  │ summary   │       │ summary   │       │ summary   │     │
│  └─────┬─────┘       └─────┬─────┘       └─────┬─────┘     │
│        │                   │                   │            │
│        └─────── artifacts ─┴─────── artifacts ─┘            │
│                            ↓                                 │
│                   ai-run-summary job                        │
│                            ↓                                 │
│                   Markdown + PNG → Slack                    │
└─────────────────────────────────────────────────────────────┘
```

Each stage is a **GitHub composite action** — drop into any workflow.

---

## Slide 5 — How a Job Gets Classified

```
  .log files
      │
      ▼
  ┌─────────────────────────────────────────────────┐
  │ 1. Extract signals                              │
  │    Scan logs for known patterns per category:   │
  │    infra · hw · tt-metal · vllm · model         │
  └─────────────────────────────────────────────────┘
      │
      ▼
  ┌─────────────────────────────────────────────────┐
  │ 2. Initial status from signals                  │
  │    TT_FATAL / SIGSEGV   →  CRASHED              │
  │    timeout patterns     →  TIMEOUT              │
  │    pytest FAILED lines  →  TESTS_FAILED         │
  │    no failure signals   →  SUCCESS  (stop here) │
  └─────────────────────────────────────────────────┘
      │  (only if failing)
      ▼
  ┌─────────────────────────────────────────────────┐
  │ 3. LLM analysis                                 │
  │    An LLM (default: Claude Sonnet, configurable │
  │    in analysis.yaml) reads the extracted logs   │
  │    and returns:                                 │
  │      - root cause                               │
  │      - which layer broke                        │
  │      - suggested action                         │
  │    Can refine the status                        │
  │    (e.g. TESTS_FAILED → CRASHED when the server │
  │     never started)                              │
  └─────────────────────────────────────────────────┘
```

**SUCCESS jobs skip the LLM entirely** — zero cost on green runs.

---

## Slide 6 — Status Model

Every job ends up with one of these statuses:

| Status | Color | Meaning |
|--------|-------|---------|
| **SUCCESS** | 🟢 | Tests passed, no errors |
| **TESTS_FAILED** | 🟠 | Tests ran, some failed |
| **EVALS_BELOW_TARGET** | 🟡 | Tests passed but accuracy too low |
| **CRASHED** | 🔴 | Process died — TT_FATAL, segfault, uncaught exception |
| **TIMEOUT** | 🔴 | Hung or exceeded time budget |
| **FAILED** | 🔴 | Non-zero exit, no specific signal matched |
| **INFRA_FAILURE** | 🟣 | Runner died, missing logs, or no artifact produced |

The *status* axis is always one of the above. Classification ambiguity lives
in the separate *category* field (`unknown` when LLM can't pin a root cause).

---

## Slide 7 — Config: Bundled + Per-Repo Override

**The tool ships with `analysis.yaml`** — default categories, patterns, LLM prompt.
Covers TT-Metal, vLLM, TTNN, model evals, standard infra.

**Each repo adds its own config** — points at log directories, declares project-specific patterns:

```yaml
# .github/ai-summary/vllm-nightly.yaml
job_summary:
  log_dirs: [docker-job/output]
  output_dir: docker-job/ai_summaries
run_summary:
  summary_dir: ai_job_summaries
  output_dir: ai_run_summaries
```

Three-layer merge: bundled defaults → workflow YAML → optional per-repo extension.
New patterns land in `analysis.yaml` and everyone benefits immediately.

---

## Slide 8 — Infra Failure Detection

A leg that **never writes a log** is the hardest case — there's nothing to extract.

**Solution: workflow-native data flow.** The run-summary job receives two
inputs straight from the matrix job via the native `needs.*` context:

- `expected-jobs: ${{ needs.<matrix-job>.outputs.matrix }}` — the list of
  expected leg names, already produced by a `generate-matrix` job.
- `run-result: ${{ needs.<matrix-job>.result }}` — aggregate outcome.

No extra artifact upload, no GitHub API round-trip, no env-var smuggling.

Missing leg → synthetic `INFRA_FAILURE` entry with `category: infra:no_artifact`
(*"Runner setup failed or the runner never picked up the job"*).

When `run-result` is `cancelled` or `skipped`, synthesis is suppressed — the
user aborted or the matrix was gated off, so there's nothing to reconcile.

No more silently-missing jobs.

---

## Slide 9 — Integration: Two Steps

**In each matrix leg:**
```yaml
- name: 🤖 AI job summary
  if: always() && !cancelled()
  uses: tenstorrent/tt-github-actions/.github/actions/ai_job_summary@main
  with:
    config-path: .github/ai-summary/<workflow>.yaml
    api-key: ${{ secrets.TT_CHAT_API_KEY }}
    api-url: ${{ secrets.TT_CHAT_URL }}
```

**One aggregation job after the matrix:**
```yaml
ai-run-summary:
  needs: [generate-matrix, matrix-job]
  if: always()
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: tenstorrent/tt-github-actions/.github/actions/ai_run_summary@main
      with:
        config-path: .github/workflows/<workflow>-ai-summary-config.yaml
        expected-jobs: ${{ needs.generate-matrix.outputs.matrix }}
        run-result: ${{ needs.matrix-job.result }}
        slack-bot-token: ${{ secrets.SLACK_BOT_TOKEN }}
        slack-channel-id: ${{ secrets.SLACK_CHANNEL_ID }}
```

That's the entire integration.

---

## Slide 10 — Where We Are

- ✅ Extracted from `tt-shield` into reusable `tt-github-actions` repo
- ✅ Wired into **vLLM nightly** in `tt-metal` (live on branch)
- ✅ 282 unit + integration tests passing
- ✅ Clean packaging (hatchling build, self-contained install)
- ✅ INFRA_FAILURE detection via `expected-jobs` + `run-result` caller inputs
- ✅ Three-layer config merge working end-to-end
- ✅ Slack delivery working

**Real win:** correctly classified crash-vs-test-failure-vs-infra across a
real failing nightly (BH, T3K, QB-GE, LB matrix).

---

## Slide 11 — What's Next

**Short term**
- Land in `tenstorrent/tt-github-actions` main
- Replace current ad-hoc log dumps in other nightlies

**Medium term**
- Extend to **All Model Tests** (3 impl workflows, dynamic matrix)
- Expose a shared Grafana/Slack board of recent runs
- LLM-written narrative at the run level ("what's broken this morning")

**Longer term**
- Historical trend analysis — "this category has regressed 3x in the last week"
- Auto-file issues for specific failure patterns
- Feedback loop: engineers label a summary as right/wrong, tune prompts

---

## Slide 12 — Why It Matters

A nightly that took 20 minutes to triage now takes **30 seconds** —
scan one Slack message, click through only the summaries that need eyes.

That time goes back into the work that actually moves the product forward.

**Questions?**
