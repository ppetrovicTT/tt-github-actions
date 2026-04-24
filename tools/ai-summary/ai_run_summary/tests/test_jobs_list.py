# SPDX-FileCopyrightText: (c) 2026 Tenstorrent AI ULC
#
# SPDX-License-Identifier: Apache-2.0
"""Tests for the GHA jobs-list reconciliation."""

from __future__ import annotations

import json
from pathlib import Path

from ai_run_summary.jobs_list import apply_jobs_list


def _write_jobs(tmp: Path, jobs: list[dict]) -> Path:
    f = tmp / "jobs.json"
    f.write_text(json.dumps(jobs))
    return f


def _write_summary(summary_dir: Path, name: str, status: str = "SUCCESS") -> Path:
    summary_dir.mkdir(parents=True, exist_ok=True)
    path = summary_dir / f"ai_job_summary_{abs(hash(name))}.json"
    path.write_text(json.dumps({"_job": {"name": name, "status": status}}))
    return path


class TestApplyJobsList:
    def test_stubs_infra_failure_for_missing_failed_leg(self, tmp_path):
        summary_dir = tmp_path / "summaries"
        summary_dir.mkdir()
        jobs = _write_jobs(tmp_path, [
            {"name": "vllm-tests / [N150] Alpha", "conclusion": "failure"},
            {"name": "vllm-tests / [N150] Beta",  "conclusion": "success"},
        ])
        _write_summary(summary_dir, "[N150] Beta")

        stats = apply_jobs_list(summary_dir, jobs, jobs_filter="vllm-tests / ")

        assert stats == {"cancelled_dropped": 0, "infra_stubbed": 1, "success_overridden": 0}
        produced = [json.loads(f.read_text()) for f in summary_dir.glob("*.json")]
        names = {d["_job"]["name"]: d["_job"]["status"] for d in produced}
        assert names == {"[N150] Alpha": "INFRA_FAILURE", "[N150] Beta": "SUCCESS"}

    def test_drops_cancelled_legs(self, tmp_path):
        summary_dir = tmp_path / "summaries"
        _write_summary(summary_dir, "[N150] Cancelled", status="SUCCESS")
        _write_summary(summary_dir, "[N150] Good",      status="SUCCESS")
        jobs = _write_jobs(tmp_path, [
            {"name": "vllm-tests / [N150] Cancelled", "conclusion": "cancelled"},
            {"name": "vllm-tests / [N150] Good",      "conclusion": "success"},
        ])

        stats = apply_jobs_list(summary_dir, jobs, jobs_filter="vllm-tests / ")

        assert stats["cancelled_dropped"] == 1
        remaining = {json.loads(f.read_text())["_job"]["name"] for f in summary_dir.glob("*.json")}
        assert remaining == {"[N150] Good"}

    def test_overrides_success_to_unknown_when_gha_says_failure(self, tmp_path):
        summary_dir = tmp_path / "summaries"
        _write_summary(summary_dir, "[N150] Sneaky", status="SUCCESS")
        jobs = _write_jobs(tmp_path, [
            {"name": "vllm-tests / [N150] Sneaky", "conclusion": "failure"},
        ])

        stats = apply_jobs_list(summary_dir, jobs, jobs_filter="vllm-tests / ")

        assert stats["success_overridden"] == 1
        data = json.loads(next(summary_dir.glob("*.json")).read_text())
        assert data["_job"]["status"] == "UNKNOWN"
        assert data["category"] == "unknown:gha_failure"

    def test_does_not_override_non_success_statuses(self, tmp_path):
        summary_dir = tmp_path / "summaries"
        _write_summary(summary_dir, "[N150] Crashed", status="CRASHED")
        jobs = _write_jobs(tmp_path, [
            {"name": "vllm-tests / [N150] Crashed", "conclusion": "failure"},
        ])

        stats = apply_jobs_list(summary_dir, jobs, jobs_filter="vllm-tests / ")

        assert stats["success_overridden"] == 0
        data = json.loads(next(summary_dir.glob("*.json")).read_text())
        assert data["_job"]["status"] == "CRASHED"

    def test_timeout_stubs_and_overrides(self, tmp_path):
        summary_dir = tmp_path / "summaries"
        jobs = _write_jobs(tmp_path, [
            {"name": "vllm-tests / [N150] Slow",  "conclusion": "timed_out"},
        ])

        stats = apply_jobs_list(summary_dir, jobs, jobs_filter="vllm-tests / ")

        assert stats["infra_stubbed"] == 1
        data = json.loads(next(summary_dir.glob("*.json")).read_text())
        assert data["_job"]["status"] == "INFRA_FAILURE"
        assert "timed out" in data["root_cause"].lower()

    def test_filter_excludes_non_matching_jobs(self, tmp_path):
        summary_dir = tmp_path / "summaries"
        summary_dir.mkdir()
        jobs = _write_jobs(tmp_path, [
            {"name": "build-artifact / compile",      "conclusion": "failure"},
            {"name": "vllm-tests / generate-matrix",  "conclusion": "success"},
            {"name": "vllm-tests / [N150] Alpha",     "conclusion": "failure"},
        ])

        # Filter picks only jobs whose name contains '[N150]'
        stats = apply_jobs_list(summary_dir, jobs, jobs_filter="[N150]")

        assert stats["infra_stubbed"] == 1
        remaining = {json.loads(f.read_text())["_job"]["name"] for f in summary_dir.glob("*.json")}
        assert remaining == {"[N150] Alpha"}

    def test_orchestrator_jobs_with_no_artifact_are_silently_skipped(self, tmp_path):
        summary_dir = tmp_path / "summaries"
        summary_dir.mkdir()
        jobs = _write_jobs(tmp_path, [
            {"name": "vllm-tests / generate-matrix", "conclusion": "success"},
        ])

        stats = apply_jobs_list(summary_dir, jobs, jobs_filter="vllm-tests / ")

        assert stats == {"cancelled_dropped": 0, "infra_stubbed": 0, "success_overridden": 0}
        assert not list(summary_dir.glob("*.json"))

    def test_null_conclusion_is_ignored(self, tmp_path):
        """In-progress jobs have conclusion=None; must not stub or crash."""
        summary_dir = tmp_path / "summaries"
        summary_dir.mkdir()
        jobs = _write_jobs(tmp_path, [
            {"name": "vllm-tests / [N150] Alpha", "conclusion": None},
        ])

        stats = apply_jobs_list(summary_dir, jobs, jobs_filter="vllm-tests / ")

        assert stats == {"cancelled_dropped": 0, "infra_stubbed": 0, "success_overridden": 0}
