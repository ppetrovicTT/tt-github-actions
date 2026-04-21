# SPDX-FileCopyrightText: (c) 2026 Tenstorrent AI ULC
#
# SPDX-License-Identifier: Apache-2.0
"""Detect jobs from a matrix manifest that produced no AI summary and stub them as INFRA_FAILURE."""

from __future__ import annotations

import json
from pathlib import Path


def _received_job_names(summary_dir: Path) -> set[str]:
    names: set[str] = set()
    for f in summary_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            name = data.get("_job", {}).get("name", "")
            if name:
                names.add(name)
        except (json.JSONDecodeError, OSError):
            pass
    return names


def apply_manifest(summary_dir: Path, manifest_path: Path) -> int:
    """Create INFRA_FAILURE stubs for expected jobs with no summary.

    Reads manifest_path (list of {name: str}), compares against summaries
    already in summary_dir, and writes one stub JSON per missing job.
    Returns the number of stubs created.
    """
    expected: list[dict] = json.loads(manifest_path.read_text())
    received = _received_job_names(summary_dir)

    summary_dir.mkdir(parents=True, exist_ok=True)
    created = 0
    for entry in expected:
        name = entry.get("name", "")
        if not name or name in received:
            continue
        stub_path = summary_dir / f"ai_job_summary_stub_{abs(hash(name))}.json"
        if stub_path.exists():
            continue
        stub_path.write_text(json.dumps({
            "_job": {
                "name": name,
                "url": "",
                "status": "INFRA_FAILURE",
            },
            "category": "infra:runner",
            "root_cause": "Job did not start or complete — no summary received",
        }, indent=2))
        created += 1
    return created
