# SPDX-FileCopyrightText: (c) 2026 Tenstorrent AI ULC
#
# SPDX-License-Identifier: Apache-2.0
"""
Command-line interface for AI Run Summary.

Usage:
    ai-run-summary --config <config.yaml>
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path

from ai_job_summary.config import load_config
from common.llm_client import get_llm_client

from .aggregate import compute_stats
from .format import format_run_report
from .narrative import generate_narrative
from .parse import parse_summaries_dir


def _should_call_llm(config: dict) -> bool:
    """Check if LLM should be called based on config model field."""
    model = config.get("model", "")
    return bool(model) and model.lower() != "none"


def _received_names(summary_dir: Path) -> set[str]:
    """Return names of jobs that produced an ai-job-summary artifact."""
    import json as _json
    names: set[str] = set()
    for f in summary_dir.glob("*.json"):
        try:
            data = _json.loads(f.read_text())
            name = data.get("_job", {}).get("name", "")
            if name:
                names.add(name)
        except (ValueError, OSError):
            pass
    return names


def _stub_infra(summary_dir: Path, name: str) -> None:
    """Write an INFRA_FAILURE stub for an expected leg that never reported."""
    import json as _json
    summary_dir.mkdir(parents=True, exist_ok=True)
    path = summary_dir / f"ai_job_summary_{abs(hash(name))}.json"
    path.write_text(_json.dumps({
        "_job": {"name": name, "status": "INFRA_FAILURE"},
        "category": "infra:no_artifact",
        "root_cause": (
            "Job produced no ai-job-summary artifact. Likely cause: "
            "container/runner setup failure, runner never picked up the job, "
            "or the runner was killed before ai-job-summary could run. "
            "Check the GitHub Actions logs for the individual job."
        ),
    }, indent=2))


def synthesize_missing_legs(
    summary_dir: Path,
    expected_jobs: "str | list[dict] | Path",
    run_result: str,
) -> dict[str, int]:
    """Synthesize INFRA_FAILURE stubs for expected jobs that produced no artifact.

    Args:
        summary_dir:   Directory containing per-leg ai_job_summary_*.json files.
        expected_jobs: The generate-matrix output. Accepted forms:
                         - a JSON string (from ${{ needs.x.outputs.matrix }}),
                         - an already-parsed list of dicts,
                         - a pathlib.Path to a JSON file (for local use / tests).
                       Each entry must have a "name" matching _job.name in artifacts.
        run_result:    The matrix job's aggregate needs.<>.result:
                       'success' | 'failure' | 'cancelled' | 'skipped'.
                       Synthesis is skipped when cancelled.

    Returns: {"infra_stubbed": n}
    """
    import json as _json
    if run_result.lower() == "cancelled":
        return {"infra_stubbed": 0}

    if isinstance(expected_jobs, Path):
        jobs = _json.loads(expected_jobs.read_text())
    elif isinstance(expected_jobs, str):
        jobs = _json.loads(expected_jobs) if expected_jobs.strip() else []
    else:
        jobs = expected_jobs

    received = _received_names(summary_dir)
    stubbed = 0
    for job in jobs:
        name = job.get("name", "")
        if not name or name in received:
            continue
        _stub_infra(summary_dir, name)
        stubbed += 1
    return {"infra_stubbed": stubbed}


def _resolve_run_metadata() -> dict:
    """Gather run metadata from environment variables.

    Works with GitHub Actions, GitLab CI, or plain invocation.
    Returns dict with keys: run_url, run_id, run_date, pr
    """
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    server = os.environ.get("GITHUB_SERVER_URL", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")

    run_url = ""
    if server and repo and run_id:
        run_url = f"{server}/{repo}/actions/runs/{run_id}"

    pr = ""
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    ref = os.environ.get("GITHUB_REF", "")
    if event == "pull_request" and "/pull/" in ref:
        pr = ref.split("/pull/")[1].split("/")[0]

    return {
        "run_url": run_url,
        "run_id": run_id,
        "run_date": datetime.date.today().isoformat(),
        "pr": pr,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Aggregate per-job AI summaries into a run-level report",
    )
    parser.add_argument("--config", required=True, help="Path to project config YAML")
    parser.add_argument("--expected-jobs", type=str, default="",
                        help="JSON array of expected matrix legs (from "
                             "needs.<matrix-job>.outputs.matrix). Each entry must "
                             "have a 'name' field. Used to synthesize INFRA_FAILURE "
                             "stubs for legs that produced no artifact.")
    parser.add_argument("--run-result", type=str, default="",
                        help="Aggregate result of the matrix job from "
                             "needs.<matrix-job>.result: 'success' | 'failure' | "
                             "'cancelled' | 'skipped'. No stubs are synthesized "
                             "when 'cancelled'.")

    args = parser.parse_args()

    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    config = load_config(config_path)

    run_cfg = config.get("run_summary", {})
    summary_dir = run_cfg.get("summary_dir")
    output_dir = run_cfg.get("output_dir")

    if not summary_dir:
        print("Error: config must specify run_summary.summary_dir", file=sys.stderr)
        sys.exit(1)
    if not output_dir:
        print("Error: config must specify run_summary.output_dir", file=sys.stderr)
        sys.exit(1)

    summaries_dir = Path(summary_dir)

    # Synthesize INFRA_FAILURE stubs for expected matrix legs that produced no
    # artifact. Skipped when run_result=cancelled (user cancelled; don't fabricate
    # rows for legs that never ran).
    if args.expected_jobs and args.run_result:
        stats = synthesize_missing_legs(
            summaries_dir, args.expected_jobs, run_result=args.run_result,
        )
        if stats["infra_stubbed"]:
            print(f"Stubbed {stats['infra_stubbed']} INFRA_FAILURE leg(s) with no summary",
                  file=sys.stderr)

    # Set model from config
    model = config.get("model", "")
    if model:
        os.environ.setdefault("TT_CHAT_MODEL", model)

    # Parse summaries
    print(f"Scanning {summaries_dir} for summaries...", file=sys.stderr)
    summaries = parse_summaries_dir(summaries_dir)
    print(f"Parsed {len(summaries)} summary files", file=sys.stderr)

    if not summaries:
        print("Warning: No summary files found", file=sys.stderr)

    # Compute stats
    stats = compute_stats(summaries)

    # Generate LLM narrative (if model is set and not "none")
    narrative = None
    if _should_call_llm(config):
        try:
            llm_client = get_llm_client()
            print("Calling LLM...", file=sys.stderr)
            narrative = generate_narrative(stats, llm_client=llm_client)
            print(
                f"Done in {narrative.response_time_ms:.0f}ms "
                f"({narrative.prompt_tokens}+{narrative.completion_tokens} tokens)",
                file=sys.stderr,
            )
        except ValueError as e:
            print(f"Warning: LLM skipped: {e}", file=sys.stderr)
        except RuntimeError as e:
            print(f"Warning: LLM call failed: {e}", file=sys.stderr)

    # Resolve run metadata from environment
    meta = _resolve_run_metadata()

    # Format report
    report = format_run_report(
        stats,
        narrative=narrative,
        run_url=meta["run_url"],
        run_id=meta["run_id"],
        run_date=meta["run_date"],
        pr=meta["pr"],
    )

    # Write report to output_dir
    run_id = meta["run_id"] or "local"
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    stem = f"ai_run_summary_{run_id}"
    (out / f"{stem}.md").write_text(report.md)
    (out / f"{stem}.html").write_text(report.html)
    print(f"Report written to: {out / stem}.md", file=sys.stderr)


if __name__ == "__main__":
    main()
