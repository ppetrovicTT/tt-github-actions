# SPDX-FileCopyrightText: (c) 2026 Tenstorrent AI ULC
#
# SPDX-License-Identifier: Apache-2.0
"""
Level 1 extraction unit tests.

Each test exercises extract_log() directly on a real log fixture and
asserts the most meaningful extraction signals for each failure category.
"""

import pytest

from ai_job_summary.extract import ExtractedLog, extract_log, merge_log_files

from .conftest import FIXTURE_LOG_DIR as FIXTURE_DIR


def _errors_text(result: ExtractedLog) -> str:
    """Join all error sections into one searchable string."""
    return "\n".join(result.error_sections).lower()


# ── app:cli — argparse error, server never started ────────────────────────────


class TestAppCliArgparse:
    """
    Log: app_cli_argparse.log
    Root cause: argparse rejects --num-scheduler-steps → server exits before start.
    Downstream health-check timeouts are symptoms, not the root cause.
    """

    @pytest.fixture(scope="class")
    def extracted(self):
        return extract_log(FIXTURE_DIR / "app_cli_argparse.txt")

    def test_has_crash_is_false(self, extracted):
        """Server exited with argparse error, not a TT_FATAL / panic crash."""
        assert extracted.has_crash is False

    def test_error_sections_contain_unrecognized_arguments(self, extracted):
        """Primary error must appear in extracted sections."""
        assert "unrecognized arguments" in _errors_text(extracted), (
            "Expected 'unrecognized arguments' in error sections"
        )

    def test_first_error_section_contains_argparse_error(self, extracted):
        """Error Section 1 should be the argparse rejection, not a downstream timeout."""
        assert extracted.error_sections, "Expected at least one error section"
        first = extracted.error_sections[0].lower()
        assert "unrecognized arguments" in first or "error:" in first, (
            f"Expected argparse error in first section, got: {first[:300]}"
        )

    def test_no_health_check_timeout_as_primary_error(self, extracted):
        """
        The health-check timeout ('did not become healthy') is a downstream symptom.
        It must NOT appear as the first error section (root cause must come first).
        """
        if not extracted.error_sections:
            pytest.skip("No error sections extracted")
        first = extracted.error_sections[0].lower()
        # The FIRST section should be the argparse error, not the timeout symptom
        assert "did not become healthy" not in first, (
            "Health-check timeout should not be the primary/first error section"
        )

    def test_error_sections_not_empty(self, extracted):
        assert len(extracted.error_sections) >= 1


# ── vllm:config — max_model_len exceeds device limit ─────────────────────────


class TestVllmConfigError:
    """
    Log: vllm_config_error.log
    Root cause: max_model_len=65536 exceeds N150 limit of 32768.
    """

    @pytest.fixture(scope="class")
    def extracted(self):
        return extract_log(FIXTURE_DIR / "vllm_config_error.txt")

    def test_error_sections_contain_max_model_len(self, extracted):
        """The vLLM config error must mention max_model_len or max_mo."""
        errors = _errors_text(extracted)
        assert "max_model_len" in errors or "max_mo" in errors, (
            "Expected 'max_model_len' or 'max_mo' in error sections"
        )

    def test_error_sections_contain_value_error(self, extracted):
        """ValueError must be reported."""
        assert "valueerror" in _errors_text(extracted)

    def test_error_sections_not_empty(self, extracted):
        assert len(extracted.error_sections) >= 1

    def test_has_crash_is_false(self, extracted):
        """vLLM config rejection is not a TT_FATAL crash."""
        assert extracted.has_crash is False


# ── tt-metal:fabric — Ethernet core timeout ───────────────────────────────────


class TestTtMetalFabricTimeout:
    """
    Log: tt_metal_fabric_timeout.log
    Root cause: RuntimeError: Timeout waiting for Ethernet core service.
    """

    @pytest.fixture(scope="class")
    def extracted(self):
        return extract_log(FIXTURE_DIR / "tt_metal_fabric_timeout.txt")

    def test_error_sections_contain_ethernet(self, extracted):
        """Ethernet error must appear in extracted sections."""
        errors = _errors_text(extracted)
        assert "ethernet" in errors, (
            "Expected 'Ethernet' in error sections for tt-metal:fabric failure"
        )

    def test_error_sections_contain_runtime_error(self, extracted):
        """RuntimeError must be captured."""
        assert "runtimeerror" in _errors_text(extracted)

    def test_either_crash_or_timeout_or_ethernet_error(self, extracted):
        """At least one of: has_crash, has_timeout, or Ethernet error in sections."""
        errors = _errors_text(extracted)
        assert (
            extracted.has_crash
            or extracted.has_timeout
            or "ethernet" in errors
        ), "Expected crash, timeout, or Ethernet error signal"

    def test_error_sections_not_empty(self, extracted):
        assert len(extracted.error_sections) >= 1


# ── infra:network — DNS resolution failure ────────────────────────────────────


class TestInfraNetworkDns:
    """
    Log: infra_network_dns.log
    Root cause: Failed to resolve 'huggingface.co' — DNS failure.
    """

    @pytest.fixture(scope="class")
    def extracted(self):
        return extract_log(FIXTURE_DIR / "infra_network_dns.txt")

    def test_error_sections_contain_huggingface(self, extracted):
        """DNS failure must reference the unreachable host."""
        assert "huggingface" in _errors_text(extracted), (
            "Expected 'huggingface' in error sections for DNS failure"
        )

    def test_error_sections_contain_resolve_keyword(self, extracted):
        """'resolve' or 'resolution' must appear in error sections."""
        errors = _errors_text(extracted)
        assert "resolve" in errors or "resolution" in errors, (
            "Expected DNS resolution keyword in error sections"
        )

    def test_error_sections_not_empty(self, extracted):
        assert len(extracted.error_sections) >= 1

    def test_has_crash_is_false(self, extracted):
        """DNS failure is not a TT_FATAL crash."""
        assert extracted.has_crash is False


# ── UNKNOWN — lmms_eval task not found ───────────────────────────────────────


class TestUnknownLmmsEval:
    """
    Log: unknown_lmms_eval.log
    Root cause: ValueError: Tasks not found: librispeech_test_other
    Category: UNKNOWN (not in known patterns).
    """

    @pytest.fixture(scope="class")
    def extracted(self):
        return extract_log(FIXTURE_DIR / "unknown_lmms_eval.txt")

    def test_error_sections_contain_tasks_not_found(self, extracted):
        """Tasks not found error must appear in extracted sections."""
        errors = _errors_text(extracted)
        assert "tasks not found" in errors, (
            "Expected 'Tasks not found' in error sections for UNKNOWN lmms_eval failure"
        )

    def test_error_sections_not_empty(self, extracted):
        assert len(extracted.error_sections) >= 1

    def test_has_crash_is_false(self, extracted):
        """Task-not-found is not a hard crash."""
        assert extracted.has_crash is False


# ── model:load — KeyError on unsupported mesh config ─────────────────────────


class TestModelLoadFailure:
    """
    Log: model_load_failure.log
    Root cause: KeyError: (1, 4) — mesh config not in default_config dict.
    """

    @pytest.fixture(scope="class")
    def extracted(self):
        return extract_log(FIXTURE_DIR / "model_load_failure.txt")

    def test_error_sections_contain_key_error(self, extracted):
        """KeyError must appear in extracted error sections."""
        assert "keyerror" in _errors_text(extracted), (
            "Expected 'KeyError' in error sections for model:load failure"
        )

    def test_error_sections_not_empty(self, extracted):
        assert len(extracted.error_sections) >= 1

    def test_has_crash_is_false(self, extracted):
        """Python KeyError during load is not a TT_FATAL crash."""
        assert extracted.has_crash is False

    def test_error_sections_signal_some_failure(self, extracted):
        """At minimum, there should be error content extracted."""
        assert len(extracted.error_sections) > 0
        total_chars = sum(len(s) for s in extracted.error_sections)
        assert total_chars > 50, "Error sections should contain substantive content"


# ── model:accuracy — FLUX.1-schnell FID/CLIP below threshold ─────────────────


class TestModelEvalsBelow:
    """
    Log: model_evals_below_target.txt
    Root cause: FLUX.1-schnell FID score 204.12 and CLIP score 29.03 both fail
    quality thresholds. The server ran fine — only the eval metrics are out of range.
    """

    @pytest.fixture(scope="class")
    def extracted(self):
        return extract_log(FIXTURE_DIR / "model_evals_below_target.txt")

    def test_eval_failure_signals_present(self, extracted):
        """Eval failure signals must appear somewhere in the extraction."""
        errors = _errors_text(extracted)
        assert "fid" in errors and ("clip" in errors or "failed" in errors), (
            "Expected FID score and evaluation failure signal in extracted error sections"
        )

    def test_has_crash_is_false(self, extracted):
        """Server ran correctly; only eval metrics failed — not a TT_FATAL crash."""
        assert extracted.has_crash is False


# ── SUCCESS — healthy completed run ──────────────────────────────────────────


class TestSuccess:
    """
    Log: success_healthy.txt
    All workflows completed, exit code 0, no failures.
    """

    @pytest.fixture(scope="class")
    def extracted(self):
        return extract_log(FIXTURE_DIR / "success_healthy.txt")

    def test_has_crash_is_false(self, extracted):
        assert extracted.has_crash is False

    def test_has_timeout_is_false(self, extracted):
        assert extracted.has_timeout is False

    def test_no_failed_tests(self, extracted):
        assert extracted.failed_tests == []


# ── tt-metal:memory — DRAM buffer OOM during prefill warmup ──────────────────


class TestTtMetalMemoryOom:
    """
    Log: tt_metal_memory_oom.txt
    Root cause: TT_FATAL — Out of Memory: not enough DRAM to allocate 1140850688 B buffer
    during prefill warmup for Llama-3.2-1B-Instruct on N150 with max_prefill_chunk_size=131072.
    """

    @pytest.fixture(scope="class")
    def extracted(self):
        return extract_log(FIXTURE_DIR / "tt_metal_memory_oom.txt")

    def test_error_sections_contain_oom(self, extracted):
        """OOM error must appear in extracted sections."""
        errors = _errors_text(extracted)
        assert "out of memory" in errors or "dram" in errors or "allocat" in errors, (
            "Expected OOM-related text ('Out of Memory', 'DRAM', or 'allocate') in error sections"
        )

    def test_has_crash_is_true(self, extracted):
        """TT_FATAL OOM crash must set has_crash=True."""
        assert extracted.has_crash is True

    def test_error_sections_not_empty(self, extracted):
        assert len(extracted.error_sections) >= 1


# ── tt-metal:trace — TT_FATAL trace region size exceeded ─────────────────────


class TestTtMetalTraceFatal:
    """
    Log: tt_metal_trace_fatal.txt
    Root cause: TT_FATAL at mesh_trace.cpp:182 — trace buffer (60899328B) exceeds
    allocated trace_region_size (50000000B) for Qwen3-32B on P150x8.
    """

    @pytest.fixture(scope="class")
    def extracted(self):
        return extract_log(FIXTURE_DIR / "tt_metal_trace_fatal.txt")

    def test_error_sections_contain_tt_fatal_or_tt_throw(self, extracted):
        """TT_FATAL or TT_THROW must appear in extracted sections."""
        errors = _errors_text(extracted)
        assert "tt_fatal" in errors or "tt_throw" in errors, (
            "Expected 'TT_FATAL' or 'TT_THROW' in error sections for tt-metal:trace failure"
        )

    def test_has_crash_is_true(self, extracted):
        """TT_FATAL crash must set has_crash=True."""
        assert extracted.has_crash is True

    def test_error_sections_not_empty(self, extracted):
        assert len(extracted.error_sections) >= 1


# ── tt-metal:dispatch — device timeout / potential hang ──────────────────────


class TestTtMetalDispatchTimeout:
    """
    Log: tt_metal_dispatch_timeout.txt
    Root cause: TT_THROW — device timeout in fetch queue wait during large prefill
    for gemma-3-4b-it on N300, indicating a potential dispatch hang.
    """

    @pytest.fixture(scope="class")
    def extracted(self):
        return extract_log(FIXTURE_DIR / "tt_metal_dispatch_timeout.txt")

    def test_error_sections_contain_timeout_signal(self, extracted):
        """TIMEOUT or hang signal must appear in extracted sections."""
        errors = _errors_text(extracted)
        assert "timeout" in errors or "hang" in errors, (
            "Expected 'TIMEOUT' or 'hang' in error sections for tt-metal:dispatch failure"
        )

    def test_has_crash_or_timeout(self, extracted):
        """Device timeout crash must be detected as crash or timeout."""
        assert extracted.has_crash or extracted.has_timeout, (
            "Expected has_crash=True or has_timeout=True for dispatch timeout"
        )

    def test_error_sections_not_empty(self, extracted):
        assert len(extracted.error_sections) >= 1


# ── Error section merging ────────────────────────────────────────────────────


class TestErrorSectionMerging:
    """Consecutive error lines within context_lines merge into one section."""

    def _make_log(self, tmp_path, lines):
        d = tmp_path / "logs"
        d.mkdir(exist_ok=True)
        content = "\n".join(lines) + "\n"
        (d / "test.log").write_text(content)
        return d

    def test_adjacent_errors_merge_into_one_section(self, tmp_path):
        """Two ERROR lines 1 apart → merged into one section."""
        lines = [f"line {i}" for i in range(20)]
        lines[5] = "ERROR: first problem"
        lines[6] = "ERROR: second problem"
        d = self._make_log(tmp_path, lines)
        result = extract_log([d], context_lines=2)
        assert len(result.error_sections) == 1
        assert "first problem" in result.error_sections[0]
        assert "second problem" in result.error_sections[0]

    def test_distant_errors_stay_separate(self, tmp_path):
        """Two ERROR lines far apart → two separate sections."""
        lines = [f"line {i}" for i in range(50)]
        lines[5] = "ERROR: problem A"
        lines[40] = "ERROR: problem B"
        d = self._make_log(tmp_path, lines)
        result = extract_log([d], context_lines=2)
        assert len(result.error_sections) == 2

    def test_stack_trace_merges_into_one_section(self, tmp_path):
        """10 consecutive ERROR lines → one section, not 10."""
        lines = [f"line {i}" for i in range(30)]
        for i in range(10, 20):
            lines[i] = f"ERROR: traceback frame {i}"
        d = self._make_log(tmp_path, lines)
        result = extract_log([d], context_lines=2)
        assert len(result.error_sections) == 1
        assert "traceback frame 10" in result.error_sections[0]
        assert "traceback frame 19" in result.error_sections[0]


# ── merge_log_files with multiple directories ─────────────────────────────────


class TestMergeLogFilesMultiDir:
    """Test merging .log files from multiple directories."""

    def test_merges_files_from_two_dirs(self, tmp_path):
        d1 = tmp_path / "run_logs"
        d2 = tmp_path / "docker_server"
        d1.mkdir()
        d2.mkdir()
        (d1 / "run.log").write_text("2026-01-01 00:00:01 - run started\n")
        (d2 / "server.log").write_text("2026-01-01 00:00:02 - server started\n")
        lines = merge_log_files([d1, d2])
        text = "".join(lines)
        assert "run started" in text
        assert "server started" in text

    def test_source_labels_include_dir_name(self, tmp_path):
        d1 = tmp_path / "run_logs"
        d2 = tmp_path / "docker_server"
        d1.mkdir()
        d2.mkdir()
        (d1 / "run.log").write_text("2026-01-01 00:00:01 - line1\n")
        (d2 / "server.log").write_text("2026-01-01 00:00:02 - line2\n")
        lines = merge_log_files([d1, d2])
        text = "".join(lines)
        # Multi-dir merge prefixes source labels with dir name
        assert "run_logs/" in text
        assert "docker_server/" in text

    def test_single_dir_no_prefix(self, tmp_path):
        d = tmp_path / "logs"
        d.mkdir()
        (d / "app.log").write_text("2026-01-01 00:00:01 - line1\n")
        lines = merge_log_files([d])
        text = "".join(lines)
        # Single dir — no dir name prefix in source label
        assert "logs/" not in text
