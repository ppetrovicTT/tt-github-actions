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
    parser.add_argument("--manifest", type=Path, default=None,
                        help="Matrix manifest JSON listing expected jobs (for INFRA_FAILURE stubs)")

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

    # Apply matrix manifest: stub INFRA_FAILURE for any expected job with no summary
    if args.manifest and args.manifest.exists():
        from .manifest import apply_manifest
        n = apply_manifest(summaries_dir, args.manifest)
        if n:
            print(f"Created {n} INFRA_FAILURE stub(s) for jobs with no summary", file=sys.stderr)

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
