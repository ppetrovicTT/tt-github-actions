# SPDX-FileCopyrightText: (c) 2026 Tenstorrent AI ULC
#
# SPDX-License-Identifier: Apache-2.0
"""Configuration loading utilities."""

from pathlib import Path

import yaml


def find_package_config_dir() -> Path:
    """Find the package's config directory."""
    return Path(__file__).resolve().parent / "config"


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dicts, with override taking precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            result[key] = result[key] + value
        else:
            result[key] = value
    return result


def _apply_analysis_fields(base: dict, override: dict) -> dict:
    """Merge analysis-specific fields from override onto base."""
    result = base.copy()

    if "layers" in override:
        if override.get("layers_mode") == "replace":
            result["layers"] = override["layers"]
        else:
            result["layers"] = result["layers"] + override["layers"]

    if "categories" in override:
        result["categories"] = _deep_merge(result["categories"], override["categories"])

    if "test_patterns" in override:
        result["test_patterns"] = result["test_patterns"] + override["test_patterns"]

    if "failed_test_patterns" in override:
        result["failed_test_patterns"] = result["failed_test_patterns"] + override["failed_test_patterns"]

    if "repos" in override:
        result["repos"] = _deep_merge(result["repos"], override["repos"])

    return result


def load_config(config_path: Path | None = None) -> dict:
    """Load configuration.

    Merge order (later wins):
    1. Bundled config/analysis.yaml
    2. Consumer workflow YAML at config_path
    3. File at analysis_config: path in consumer YAML (optional)
    """
    pkg_config_dir = find_package_config_dir()
    analysis_path = pkg_config_dir / "analysis.yaml"

    if analysis_path.exists():
        with open(analysis_path) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    config.setdefault("layers", [])
    config.setdefault("categories", {})
    config.setdefault("test_patterns", [])
    config.setdefault("failed_test_patterns", [])
    config.setdefault("repos", {"default_branches": ["main", "master", "dev"]})

    if config_path and config_path.exists():
        with open(config_path) as f:
            project = yaml.safe_load(f) or {}

        if "tool_dir" in project:
            raise ValueError(
                "tool_dir is no longer supported. The action resolves the tool path "
                "automatically from its own location in tenstorrent/tt-github-actions."
            )

        config = _apply_analysis_fields(config, project)

        for key, value in project.items():
            if key not in ("layers", "layers_mode", "categories", "test_patterns",
                           "failed_test_patterns", "repos"):
                config[key] = value

        if "analysis_config" in project:
            override_path = Path(project["analysis_config"])
            if not override_path.is_absolute():
                override_path = config_path.parent / override_path
            if not override_path.exists():
                raise FileNotFoundError(
                    f"analysis_config file not found: {override_path}"
                )
            with open(override_path) as f:
                override = yaml.safe_load(f) or {}
            config = _apply_analysis_fields(config, override)

    return config


def is_default_branch(branch: str, config: dict | None = None) -> bool:
    """Check if a branch is a default branch."""
    if not branch:
        return True

    if config is None:
        config = load_config()

    default_branches = config.get("repos", {}).get("default_branches", ["main", "master", "dev"])
    return branch in default_branches
