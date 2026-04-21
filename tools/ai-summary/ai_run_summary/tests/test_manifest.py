# SPDX-FileCopyrightText: (c) 2026 Tenstorrent AI ULC
#
# SPDX-License-Identifier: Apache-2.0
import json
import pytest
from pathlib import Path

from ai_run_summary.manifest import apply_manifest


def _write_manifest(tmp_path: Path, names: list[str]) -> Path:
    f = tmp_path / "matrix_manifest.json"
    f.write_text(json.dumps([{"name": n} for n in names]))
    return f


def _write_summary(directory: Path, job_name: str, status: str = "SUCCESS") -> Path:
    f = directory / f"ai_job_summary_{abs(hash(job_name))}.json"
    f.write_text(json.dumps({"_job": {"name": job_name, "status": status, "url": ""}}))
    return f


class TestApplyManifest:
    def test_no_missing_jobs_creates_no_stubs(self, tmp_path):
        summary_dir = tmp_path / "summaries"
        summary_dir.mkdir()
        names = ["[BH-LB] Llama-3.1-8B-Instruct", "[BH-QB-GE] Llama-3.1-8B-Instruct"]
        for n in names:
            _write_summary(summary_dir, n)
        manifest = _write_manifest(tmp_path, names)

        count = apply_manifest(summary_dir, manifest)

        assert count == 0
        stubs = [f for f in summary_dir.iterdir() if "stub" in f.name]
        assert stubs == []

    def test_missing_job_creates_infra_failure_stub(self, tmp_path):
        summary_dir = tmp_path / "summaries"
        summary_dir.mkdir()
        _write_summary(summary_dir, "[BH-LB] Llama-3.1-8B-Instruct")
        manifest = _write_manifest(tmp_path, [
            "[BH-LB] Llama-3.1-8B-Instruct",
            "[BH-QB-GE] Llama-3.1-8B-Instruct",  # missing
        ])

        count = apply_manifest(summary_dir, manifest)

        assert count == 1
        infra_stubs = [
            f for f in summary_dir.glob("ai_job_summary_*.json")
            if json.loads(f.read_text()).get("_job", {}).get("status") == "INFRA_FAILURE"
        ]
        assert len(infra_stubs) == 1
        data = json.loads(infra_stubs[0].read_text())
        assert data["_job"]["name"] == "[BH-QB-GE] Llama-3.1-8B-Instruct"
        assert data["category"] == "infra:runner"
        assert "root_cause" in data


    def test_all_missing_creates_stub_per_job(self, tmp_path):
        summary_dir = tmp_path / "summaries"
        summary_dir.mkdir()
        names = ["[BH-LB] Llama", "[BH-DB] Llama", "[WH-T3K] Llama"]
        manifest = _write_manifest(tmp_path, names)

        count = apply_manifest(summary_dir, manifest)

        assert count == 3
        assert len(list(summary_dir.glob("ai_job_summary_*.json"))) == 3

    def test_does_not_double_stub_existing_stub(self, tmp_path):
        summary_dir = tmp_path / "summaries"
        summary_dir.mkdir()
        manifest = _write_manifest(tmp_path, ["[BH-LB] Llama"])

        apply_manifest(summary_dir, manifest)
        count2 = apply_manifest(summary_dir, manifest)

        assert count2 == 0
        assert len(list(summary_dir.glob("ai_job_summary_*.json"))) == 1

    def test_empty_manifest_creates_no_stubs(self, tmp_path):
        summary_dir = tmp_path / "summaries"
        summary_dir.mkdir()
        manifest = _write_manifest(tmp_path, [])

        count = apply_manifest(summary_dir, manifest)

        assert count == 0

    def test_empty_summary_dir_stubs_all(self, tmp_path):
        summary_dir = tmp_path / "summaries"
        summary_dir.mkdir()
        manifest = _write_manifest(tmp_path, ["[A] job", "[B] job"])

        count = apply_manifest(summary_dir, manifest)

        assert count == 2

    def test_creates_summary_dir_if_missing(self, tmp_path):
        summary_dir = tmp_path / "summaries_nonexistent"
        manifest = _write_manifest(tmp_path, ["[A] job"])

        count = apply_manifest(summary_dir, manifest)

        assert count == 1
        assert summary_dir.is_dir()
