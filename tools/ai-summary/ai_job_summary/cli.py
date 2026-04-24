# SPDX-FileCopyrightText: (c) 2026 Tenstorrent AI ULC
#
# SPDX-License-Identifier: Apache-2.0
"""
Command-line interface for CI Job Summary.

Usage:
    ai-job-summary --config <config.yaml> [options]
"""

import argparse
import json
import os
import re
import signal
import sys
import time
from pathlib import Path

from .config import load_config
from .config_context import gather_config_context
from .context import CIContext, gather_context
from .extract import JobStatus, apply_llm_status, calculate_time_after_error, extract_log, format_duration, get_job_status
from common.llm_client import get_llm_client
from .summarize import FailureSummary, format_infra_failure_markdown, format_summary_markdown, summarize_log


def _job_id_from_url(job_url: str) -> str:
    """Parse the numeric job ID from a GitHub Actions job URL."""
    m = re.search(r"/job/(\d+)", job_url)
    return m.group(1) if m else ""


def _write_outputs(output_dir: Path, job_id: str, md: str, data: dict) -> tuple[Path, Path]:
    """Write both markdown and JSON summaries. Returns (md_path, json_path)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    # no job_id when run locally without --job-url
    stem = f"ai_job_summary_{job_id}" if job_id else "ai_job_summary"
    md_path = output_dir / f"{stem}.md"
    json_path = output_dir / f"{stem}.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {md_path} and {json_path}", file=sys.stderr)
    return md_path, json_path


def _resolve_log_dirs(log_dirs: list[str], base: Path) -> tuple[list[Path], list[str]]:
    """Resolve log_dirs relative to base. Returns (present_dirs, missing_dirs)."""
    present, missing = [], []
    for d in log_dirs:
        p = (base / d).resolve()
        if p.is_dir() and any(p.rglob("*.log")):
            present.append(p)
        else:
            missing.append(d)
    return present, missing


def _build_json(summary, job_status, extracted_log=None, llm_response=None,
                job_name: str = "", job_url: str = "") -> dict:
    """Build the JSON output dict.

    job_name/job_url from CLI args are authoritative — extracted_log values
    are fallbacks (populated from log content, may be empty for replayed logs).
    """
    output = summary.__dict__.copy()
    output["_job"] = {
        "name": job_name or (extracted_log.job_name if extracted_log else ""),
        "url": job_url or (extracted_log.job_url if extracted_log else ""),
        "status": job_status.status_text,
        "status_code": job_status.status_code,
    }
    if llm_response:
        output["_llm_usage"] = {
            "model": llm_response.model,
            "prompt_tokens": llm_response.prompt_tokens,
            "completion_tokens": llm_response.completion_tokens,
            "response_time_ms": llm_response.response_time_ms,
        }
    if extracted_log:
        output["_job"].update({
            "timestamp": extracted_log.timestamp,
            "exit_code": extracted_log.exit_code,
            "has_crash": extracted_log.has_crash,
            "has_timeout": extracted_log.has_timeout,
            "failed_tests": extracted_log.failed_tests,
        })
    return output


def _check_config(config: dict) -> None:
    """Validate required config fields. Exits with error if any are missing."""
    job_cfg = config.get("job_summary", {})
    required = {"log_dirs": "list of log directories to analyze",
                "output_dir": "directory to write summaries"}
    errors = [f"job_summary.{k} not defined ({desc})" for k, desc in required.items() if not job_cfg.get(k)]
    if errors:
        for e in errors:
            print(f"::error::{e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="AI-powered CI log summarization")

    parser.add_argument("--config", type=Path, required=True, help="Path to project config YAML")
    parser.add_argument("--validate", action="store_true",
                        help="Validate config fields and exit (used by action.yml before running)")
    parser.add_argument("--job-name", type=str, help="Job name for summary header")
    parser.add_argument("--job-url", type=str, help="Job URL for summary header link")

    args = parser.parse_args()

    # Load and validate config — always, on every invocation
    config = load_config(args.config)
    _check_config(config)

    # --validate: config is good, exit 0
    if args.validate:
        return

    # Set model from config if not already in env
    model = config.get("model", "")
    if model:
        os.environ.setdefault("TT_CHAT_MODEL", model)

    categories = {"categories": config.get("categories", {})}
    layers = {"layers": config.get("layers", [])}
    test_patterns = {
        "test_result_patterns": config.get("test_patterns", []),
        "failed_test_patterns": config.get("failed_test_patterns", []),
    }

    job_cfg = config["job_summary"]
    output_dir = Path(job_cfg["output_dir"])

    # Resolve log dirs
    log_dirs = job_cfg["log_dirs"]

    present_dirs, missing_dirs = _resolve_log_dirs(log_dirs, Path.cwd())

    if missing_dirs:
        print(f"Missing/empty log dirs: {missing_dirs}", file=sys.stderr)

    is_infra_failure = bool(missing_dirs)
    job_name = args.job_name or ""
    job_url = args.job_url or ""
    job_id = _job_id_from_url(job_url)

    # ALL dirs missing → no logs to analyze
    if missing_dirs and not present_dirs:
        infra_status = JobStatus(False, "PURPLE", "INFRA FAILURE")
        summary = FailureSummary()
        summary.category = "infra:no_logs"
        summary.root_cause = f"Missing log dirs: {missing_dirs}"
        md = format_infra_failure_markdown(job_name=job_name, job_url=job_url)
        _write_outputs(output_dir, job_id, md, _build_json(
            summary, infra_status, job_name=job_name, job_url=job_url,
        ))
        return

    # Shared 10min budget for extraction + context gathering (the pre-LLM work).
    # LLM has its own 5min timeout via the OpenAI SDK.
    def _timeout_handler(signum, frame):
        raise TimeoutError("Pre-LLM processing timed out after 10 minutes")

    old_handler = signal.SIG_DFL
    if hasattr(signal, "SIGALRM"):
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(600)

    try:
        # Extract
        t0 = time.time()
        print(f"Extracting from {[str(d) for d in present_dirs]}...", file=sys.stderr)
        extracted = extract_log(present_dirs, test_patterns=test_patterns)
        print(
            f"Extracted {extracted.extracted_lines}/{extracted.total_lines} lines "
            f"({len(extracted.error_sections)} error sections) in {(time.time()-t0)*1000:.0f}ms",
            file=sys.stderr,
        )

        job_status = get_job_status(extracted)
        print(f"Status: {job_status.status_text}", file=sys.stderr)

        # Success + no missing dirs → done
        if job_status.is_success and not is_infra_failure:
            summary = FailureSummary()
            context = CIContext()
            md = format_summary_markdown(summary, context, job_status, extracted_log=extracted)
            _write_outputs(output_dir, job_id, md, _build_json(
                summary, job_status, extracted, job_name=job_name, job_url=job_url,
            ))
            return

        # Partial dirs + no errors → INFRA_FAILURE without LLM
        if job_status.is_success and is_infra_failure and not extracted.error_sections:
            infra_status = JobStatus(False, "PURPLE", "INFRA FAILURE")
            summary = FailureSummary()
            summary.category = "infra:partial_logs"
            summary.root_cause = f"Missing log dirs: {missing_dirs}"
            md = format_infra_failure_markdown(job_name=job_name, job_url=job_url)
            _write_outputs(output_dir, job_id, md, _build_json(
                summary, infra_status, extracted, job_name=job_name, job_url=job_url,
            ))
            return

        # Errors found — call LLM for classification.
        if is_infra_failure:
            print(f"Partial logs have errors — calling LLM for root cause analysis", file=sys.stderr)

        # Gather context
        t1 = time.time()
        log_head = "".join(extracted.raw_lines)[:50000]
        context = gather_context(repo_path=Path.cwd(), log_content=log_head)
        print(f"Context gathered in {(time.time()-t1)*1000:.0f}ms", file=sys.stderr)

        t1 = time.time()
        error_content = "\n".join(extracted.error_sections)
        config_context = gather_config_context(
            log_content=log_head, error_content=error_content,
            repo_paths=context.code.repo_paths, log_path=present_dirs[0] if present_dirs else None,
        )
        print(f"Config context gathered in {(time.time()-t1)*1000:.0f}ms", file=sys.stderr)

    except TimeoutError as e:
        print(f"::warning::{e}", file=sys.stderr)
        infra_status = JobStatus(False, "PURPLE", "INFRA FAILURE")
        summary = FailureSummary()
        summary.category = "infra:timeout"
        summary.root_cause = str(e)
        md = format_infra_failure_markdown(job_name=job_name, job_url=job_url)
        _write_outputs(output_dir, job_id, md, _build_json(
            summary, infra_status, job_name=job_name, job_url=job_url,
        ))
        return
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    # LLM (has its own 5min timeout via OpenAI SDK)
    try:
        llm_client = get_llm_client()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Using LLM: {llm_client}", file=sys.stderr)
    result = summarize_log(
        extracted_log=extracted, context=context, categories=categories,
        layers=layers, llm_client=llm_client, config_context=config_context,
    )

    resp = result.llm_response
    print(f"Done in {resp.response_time_ms:.0f}ms ({resp.prompt_tokens}+{resp.completion_tokens} tokens)", file=sys.stderr)

    # If LLM classified root cause as infra, promote to INFRA_FAILURE
    if result.summary.category and result.summary.category.startswith("infra"):
        is_infra_failure = True

    if is_infra_failure:
        job_status = JobStatus(False, "PURPLE", "INFRA FAILURE")
    else:
        job_status = apply_llm_status(job_status, result.summary.status)

    if result.summary.error_message:
        calculate_time_after_error(result.summary.error_message, extracted)
        if extracted.time_after_crash_seconds is not None:
            print(f"Time after error: {format_duration(extracted.time_after_crash_seconds)}", file=sys.stderr)

    md = format_summary_markdown(result.summary, context, job_status, resp, extracted)
    _write_outputs(output_dir, job_id, md, _build_json(
        result.summary, job_status, extracted, resp, job_name=job_name, job_url=job_url,
    ))


if __name__ == "__main__":
    main()
