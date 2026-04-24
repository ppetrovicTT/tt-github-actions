# SPDX-FileCopyrightText: (c) 2026 Tenstorrent AI ULC
#
# SPDX-License-Identifier: Apache-2.0
"""Reconcile per-job summaries against the authoritative GitHub Actions jobs list.

Replaces the older matrix-manifest approach. The caller passes a JSON list
produced by a GH API query (listJobsForWorkflowRun). That list is the single
source of truth for:

- which legs were expected to run,
- whether each leg succeeded, failed, timed out, or was cancelled.

We drop cancelled legs (per policy), stub INFRA_FAILURE for failed legs
that produced no summary, and override SUCCESS -> UNKNOWN on artifacts that
disagree with the GHA conclusion.
"""

from __future__ import annotations

import json
from pathlib import Path


def _received_map(summary_dir: Path) -> dict[str, Path]:
    """Return {job_name: path_to_json} for already-uploaded summaries."""
    m: dict[str, Path] = {}
    for f in summary_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            name = data.get("_job", {}).get("name", "")
            if name:
                m[name] = f
        except (json.JSONDecodeError, OSError):
            pass
    return m


def _leg_name(full_name: str) -> str:
    """Strip caller-job prefix from a GHA job name.

    'vllm-tests / [N150] Llama-3.1-8B-Instruct' -> '[N150] Llama-3.1-8B-Instruct'
    """
    return full_name.split(" / ", 1)[-1] if " / " in full_name else full_name


def _stub_infra(summary_dir: Path, name: str, reason: str) -> Path:
    """Write a stub JSON for a leg that produced no summary."""
    summary_dir.mkdir(parents=True, exist_ok=True)
    path = summary_dir / f"ai_job_summary_{abs(hash(name))}.json"
    path.write_text(json.dumps({
        "_job": {"name": name, "status": "INFRA_FAILURE"},
        "category": "infra:runner",
        "root_cause": reason,
    }, indent=2))
    return path


def _override_success_to_unknown(json_path: Path) -> bool:
    """If the artifact says SUCCESS, override it to UNKNOWN. Returns True if changed."""
    try:
        data = json.loads(json_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False

    current = (data.get("_job", {}).get("status") or "").upper()
    if current != "SUCCESS":
        return False

    data["_job"]["status"] = "UNKNOWN"
    data["_job"]["status_code"] = "GRAY"
    data["category"] = "unknown:gha_failure"
    data["root_cause"] = (
        "GHA job conclusion was 'failure' but the log-based classifier found "
        "no matching error patterns. Likely a pre-script / startup failure, "
        "or a pattern not yet covered by analysis.yaml."
    )
    try:
        json_path.write_text(json.dumps(data, indent=2))
    except OSError:
        return False
    return True


def apply_jobs_list(
    summary_dir: Path,
    jobs_list_path: Path,
    jobs_filter: str = "",
) -> dict[str, int]:
    """Reconcile per-leg summaries against the GHA jobs list.

    Args:
        summary_dir:     Directory containing per-leg ai_job_summary_*.json files.
        jobs_list_path:  JSON file produced by listJobsForWorkflowRun (list of
                         dicts with at least `name` and `conclusion`).
        jobs_filter:     Substring that must appear in the full job name to be
                         considered a matrix leg (e.g. 'vllm-tests / ').

    Returns a small stats dict:
        {"cancelled_dropped": n, "infra_stubbed": m, "success_overridden": k}
    """
    jobs: list[dict] = json.loads(jobs_list_path.read_text())
    received = _received_map(summary_dir)

    stats = {"cancelled_dropped": 0, "infra_stubbed": 0, "success_overridden": 0}

    for job in jobs:
        full_name = job.get("name", "")
        if jobs_filter and jobs_filter not in full_name:
            continue
        name = _leg_name(full_name)
        conclusion = (job.get("conclusion") or "").lower()

        if conclusion == "cancelled":
            # Policy: cancelled legs are dropped from the report entirely.
            if name in received:
                try:
                    received[name].unlink()
                except OSError:
                    pass
                stats["cancelled_dropped"] += 1
            continue

        if name not in received:
            # No artifact produced. Stub if the leg actually failed or timed out.
            # (conclusion == "success" with no artifact is an orchestrator job
            # like generate-matrix; silently skip.)
            if conclusion == "failure":
                _stub_infra(summary_dir, name, "Runner failed before summary could be produced")
                stats["infra_stubbed"] += 1
            elif conclusion == "timed_out":
                _stub_infra(summary_dir, name, "Job timed out before summary could be produced")
                stats["infra_stubbed"] += 1
            continue

        # Artifact present.
        if conclusion in ("failure", "timed_out"):
            if _override_success_to_unknown(received[name]):
                stats["success_overridden"] += 1

    return stats
