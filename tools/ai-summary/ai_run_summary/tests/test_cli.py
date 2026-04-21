# SPDX-FileCopyrightText: (c) 2026 Tenstorrent AI ULC
#
# SPDX-License-Identifier: Apache-2.0
"""Tests for ai_run_summary.cli."""

import json
import os
from unittest.mock import patch

import pytest
import yaml

from ai_run_summary.cli import main, _should_call_llm, _resolve_run_metadata


class TestShouldCallLlm:
    def test_none_string(self):
        assert _should_call_llm({"model": "none"}) is False

    def test_none_uppercase(self):
        assert _should_call_llm({"model": "NONE"}) is False

    def test_empty_string(self):
        assert _should_call_llm({"model": ""}) is False

    def test_missing_key(self):
        assert _should_call_llm({}) is False

    def test_valid_model(self):
        assert _should_call_llm({"model": "anthropic/claude-sonnet-4-5-20250929"}) is True


class TestResolveRunMetadata:
    def test_empty_env(self):
        with patch.dict(os.environ, {}, clear=True):
            meta = _resolve_run_metadata()
            assert meta["run_id"] == ""
            assert meta["run_url"] == ""
            assert meta["pr"] == ""
            assert meta["run_date"]  # always set to today

    def test_github_env(self):
        env = {
            "GITHUB_RUN_ID": "99999",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "org/repo",
        }
        with patch.dict(os.environ, env, clear=True):
            meta = _resolve_run_metadata()
            assert meta["run_id"] == "99999"
            assert meta["run_url"] == "https://github.com/org/repo/actions/runs/99999"

    def test_pr_detection(self):
        env = {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REF": "refs/pull/42/merge",
        }
        with patch.dict(os.environ, env, clear=True):
            meta = _resolve_run_metadata()
            assert meta["pr"] == "42"

    def test_no_pr_for_push(self):
        env = {"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main"}
        with patch.dict(os.environ, env, clear=True):
            meta = _resolve_run_metadata()
            assert meta["pr"] == ""


class TestMain:
    def _write_config(self, tmp_path, summary_dir=None, output_dir=None, model="none"):
        """Write a minimal config YAML and return its path."""
        config = {}
        if model:
            config["model"] = model
        run_summary = {}
        if summary_dir is not None:
            run_summary["summary_dir"] = str(summary_dir)
        if output_dir is not None:
            run_summary["output_dir"] = str(output_dir)
        if run_summary:
            config["run_summary"] = run_summary
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(config))
        return config_path

    def _write_summaries(self, summaries_dir):
        """Write a minimal summary JSON to the output_dir."""
        ai_dir = summaries_dir
        ai_dir.mkdir(parents=True, exist_ok=True)
        (ai_dir / "test.json").write_text(
            json.dumps(
                {
                    "_job": {
                        "name": "test-job",
                        "status": "SUCCESS",
                        "status_code": "GREEN",
                    }
                }
            )
        )
        return ai_dir

    def test_missing_config_exits(self):
        with pytest.raises(SystemExit) as exc:
            with patch("sys.argv", ["ai-run-summary"]):
                main()
        assert exc.value.code == 2

    def test_config_not_found_exits(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            with patch(
                "sys.argv",
                ["ai-run-summary", "--config", str(tmp_path / "nope.yaml")],
            ):
                main()
        assert exc.value.code == 1

    def test_missing_output_dir_exits(self, tmp_path):
        config_path = self._write_config(tmp_path, summary_dir=str(tmp_path))  # no output_dir
        with pytest.raises(SystemExit) as exc:
            with patch(
                "sys.argv", ["ai-run-summary", "--config", str(config_path)]
            ):
                main()
        assert exc.value.code == 1

    def test_missing_summary_dir_exits(self, tmp_path):
        config_path = self._write_config(tmp_path, output_dir=str(tmp_path))  # no summary_dir
        with pytest.raises(SystemExit) as exc:
            with patch(
                "sys.argv", ["ai-run-summary", "--config", str(config_path)]
            ):
                main()
        assert exc.value.code == 1

    def test_model_none_skips_llm(self, tmp_path):
        self._write_summaries(tmp_path)
        config_path = self._write_config(
            tmp_path, summary_dir=str(tmp_path), output_dir=str(tmp_path), model="none"
        )
        with patch("sys.argv", ["ai-run-summary", "--config", str(config_path)]):
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "12345"}, clear=False):
                main()
        report = tmp_path / "ai_run_summary_12345.md"
        assert report.exists()
        assert "AI Run Summary" in report.read_text()

    def test_empty_summaries_dir_warns(self, tmp_path, capsys):
        tmp_path.mkdir(parents=True, exist_ok=True)
        config_path = self._write_config(
            tmp_path, summary_dir=str(tmp_path), output_dir=str(tmp_path), model="none"
        )
        with patch(
            "sys.argv", ["ai-run-summary", "--config", str(config_path)]
        ):
            main()
        stderr = capsys.readouterr().err
        assert "No summary files found" in stderr

    def test_run_metadata_from_env(self, tmp_path):
        self._write_summaries(tmp_path)
        config_path = self._write_config(
            tmp_path, summary_dir=str(tmp_path), output_dir=str(tmp_path), model="none"
        )
        env = {
            "GITHUB_RUN_ID": "77777",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "org/repo",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("sys.argv", ["ai-run-summary", "--config", str(config_path)]):
                main()
        report = tmp_path / "ai_run_summary_77777.md"
        assert report.exists()
        assert "77777" in report.read_text()
