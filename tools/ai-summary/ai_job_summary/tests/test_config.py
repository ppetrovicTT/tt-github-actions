# SPDX-FileCopyrightText: (c) 2026 Tenstorrent AI ULC
#
# SPDX-License-Identifier: Apache-2.0
import pytest
import yaml
from pathlib import Path

from ai_job_summary.config import load_config


class TestLoadConfigPassThrough:
    def _write_config(self, tmp_path: Path, **fields) -> Path:
        f = tmp_path / "test.yaml"
        f.write_text(yaml.dump(fields))
        return f

    def test_log_dirs_passed_through(self, tmp_path):
        config = load_config(self._write_config(tmp_path, log_dirs=["a", "b"]))
        assert config["log_dirs"] == ["a", "b"]

    def test_model_passed_through(self, tmp_path):
        config = load_config(self._write_config(tmp_path, model="claude-test"))
        assert config["model"] == "claude-test"

    def test_output_dir_passed_through(self, tmp_path):
        config = load_config(self._write_config(tmp_path, output_dir="some/path"))
        assert config["output_dir"] == "some/path"

    def test_tool_dir_raises_error(self, tmp_path):
        with pytest.raises(ValueError, match="tool_dir is no longer supported"):
            load_config(self._write_config(tmp_path, tool_dir=".github/tools/ai-summary"))

    def test_categories_merged_not_passed_through(self, tmp_path):
        config = load_config(self._write_config(
            tmp_path, categories={"custom:cat": {"description": "test", "patterns": ["x"]}}
        ))
        assert "custom:cat" in config["categories"]

    def test_analysis_config_merges_categories(self, tmp_path):
        override = tmp_path / "override.yaml"
        override.write_text(yaml.dump({
            "categories": {"extra:cat": {"description": "extra", "patterns": ["extra_pattern"]}}
        }))
        consumer = self._write_config(tmp_path, analysis_config=str(override))
        config = load_config(consumer)
        assert "extra:cat" in config["categories"]

    def test_analysis_config_missing_file_raises(self, tmp_path):
        consumer = self._write_config(tmp_path, analysis_config="nonexistent.yaml")
        with pytest.raises(FileNotFoundError, match="analysis_config file not found"):
            load_config(consumer)

    def test_analysis_config_relative_to_consumer_yaml(self, tmp_path):
        subdir = tmp_path / "sub"
        subdir.mkdir()
        override = subdir / "override.yaml"
        override.write_text(yaml.dump({
            "categories": {"relative:cat": {"description": "relative", "patterns": ["rel"]}}
        }))
        consumer = tmp_path / "consumer.yaml"
        consumer.write_text(yaml.dump({"analysis_config": "sub/override.yaml"}))
        config = load_config(consumer)
        assert "relative:cat" in config["categories"]

    def test_bundled_analysis_yaml_loaded_by_default(self):
        config = load_config()
        assert "vllm:engine" in config["categories"]
        assert "tt-metal:trace" in config["categories"]
        assert config.get("model") == "anthropic/claude-sonnet-4-5-20250929"
