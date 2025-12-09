"""
tool: parallel_task
description: Deep research and enrichment using Parallel.ai Task API with async support and resume capability
parameters:
  For parallel_task_create:
    input: Task input (question or context)
    processor: Processing tier (lite, base, core, core2x, pro, ultra, ultra2x, ultra4x, ultra8x)
    task_spec: Optional output schema specification
    auto_schema: If True, API auto-generates schema (produces large JSON with basis)
    metadata: Optional user metadata dict
    source_policy: Optional domain preferences dict
    project: Optional project name for filtering/grouping results
  For parallel_task_status:
    run_id: Task run ID to check
  For parallel_task_result:
    run_id: Task run ID to get results for
    wait: If True, block until complete (default True)
    timeout: Max wait time in seconds (default 1800 = 30 min)
  For list_completed_results:
    project: Optional project name prefix to filter by
returns: Dict with run_id, status, output, and basis (citations)
"""

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

# Import progress tracking for unified status interface
from lib.progress import (
    ProgressFile,
    ProgressStatus,
    write_progress,
    update_heartbeat,
    mark_completed,
    mark_failed,
)


PARALLEL_API_BASE = "https://api.parallel.ai/v1/tasks/runs"

# Processor tiers: lite ($5/1K), base ($10/1K), core ($25/1K), core2x ($50/1K),
# pro ($100/1K), ultra ($300/1K), ultra2x ($600/1K), ultra4x ($1200/1K), ultra8x ($2400/1K)
VALID_PROCESSORS = ["lite", "base", "core", "core2x", "pro", "ultra", "ultra2x", "ultra4x", "ultra8x"]

# Data directories for persistence
PENDING_DIR = Path("data/parallel_tasks/pending")
RESULTS_DIR = Path("data/parallel_tasks/results")

# Default project for Parallel API progress files (can be overridden)
DEFAULT_PARALLEL_PROJECT = "_parallel_tasks"


def _map_parallel_status(status: str) -> ProgressStatus:
    """Map Parallel API status to ProgressStatus enum."""
    status_map = {
        "queued": ProgressStatus.PENDING,
        "processing": ProgressStatus.RUNNING,
        "completed": ProgressStatus.COMPLETED,
        "failed": ProgressStatus.FAILED,
        "error": ProgressStatus.FAILED,
    }
    return status_map.get(status.lower(), ProgressStatus.RUNNING)


def _write_parallel_progress(
    run_id: str,
    status: str,
    input_text: str = "",
    processor: str = "",
    project: Optional[str] = None,
) -> None:
    """Write/update progress file for a Parallel API task."""
    progress_status = _map_parallel_status(status)
    project = project or DEFAULT_PARALLEL_PROJECT

    progress = ProgressFile(
        run_id=run_id,
        agent="parallel-api",
        project=project,
        started_at=datetime.now(),
        status=progress_status,
        last_heartbeat=datetime.now(),
        phase=f"Parallel API: {status} (processor: {processor})" if processor else f"Parallel API: {status}",
        messages_processed=0,
        estimated_remaining="",
        error="",
        result_summary=input_text[:100] + "..." if len(input_text) > 100 else input_text,
        artifacts_created=[],
    )
    # Add backend field to distinguish from SDK agents
    progress.__dict__["backend"] = "parallel_api"
    write_progress(project, progress)


def _update_parallel_progress(
    run_id: str,
    status: str,
    project: Optional[str] = None,
) -> None:
    """Update progress file for a Parallel API task status check."""
    project = project or DEFAULT_PARALLEL_PROJECT
    progress_status = _map_parallel_status(status)

    try:
        update_heartbeat(
            project,
            run_id,
            phase=f"Parallel API: {status}",
        )
    except Exception:
        # Progress file may not exist yet, ignore
        pass


def _ensure_dirs():
    """Ensure persistence directories exist."""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _get_api_key() -> Optional[str]:
    """Get API key from environment, loading .env if needed."""
    from dotenv import load_dotenv
    load_dotenv()
    return os.environ.get("PARALLEL_API_KEY")


def _save_pending(run_id: str, data: dict):
    """Save pending task info for resume capability."""
    _ensure_dirs()
    path = PENDING_DIR / f"{run_id}.yaml"
    path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))


def _load_pending(run_id: str) -> Optional[dict]:
    """Load pending task info if exists."""
    path = PENDING_DIR / f"{run_id}.yaml"
    if path.exists():
        return yaml.safe_load(path.read_text())
    return None


def _remove_pending(run_id: str):
    """Remove pending file after task completes."""
    path = PENDING_DIR / f"{run_id}.yaml"
    if path.exists():
        path.unlink()


def _save_result(run_id: str, data: dict, project: Optional[str] = None):
    """
    Save task result for future reference.

    For large results (>5 basis items), creates directory structure:
    - data/parallel_tasks/results/{run_id}/summary.yaml
    - data/parallel_tasks/results/{run_id}/output.yaml
    - data/parallel_tasks/results/{run_id}/basis.yaml

    For small results (<=5 basis items), uses single file format:
    - data/parallel_tasks/results/{run_id}.yaml

    Args:
        run_id: Task run ID
        data: Result data from API
        project: Optional project name for filtering/grouping
    """
    _ensure_dirs()

    # Check for large basis array (auto_schema mode produces these)
    basis = data.get("basis", [])
    basis_count = len(basis) if isinstance(basis, list) else 0

    if basis_count > 5:
        # Directory format for large results
        result_dir = RESULTS_DIR / run_id
        result_dir.mkdir(parents=True, exist_ok=True)

        # Save summary
        run_info = data.get("run", {})
        output = data.get("output", {})
        summary = {
            "run_id": run_id,
            "status": run_info.get("status", "completed"),
            "completed_at": datetime.now().isoformat(),
            "has_basis": True,
            "basis_count": basis_count,
            "output_keys": list(output.keys()) if isinstance(output, dict) else [],
        }
        if project:
            summary["project"] = project
        (result_dir / "summary.yaml").write_text(yaml.dump(summary, default_flow_style=False, allow_unicode=True))

        # Save output
        (result_dir / "output.yaml").write_text(yaml.dump(output, default_flow_style=False, allow_unicode=True))

        # Save basis (citations)
        (result_dir / "basis.yaml").write_text(yaml.dump(basis, default_flow_style=False, allow_unicode=True))
    else:
        # Single file format for small results (backward compatible)
        # Add project to data if provided
        if project:
            data = {**data, "project": project}
        path = RESULTS_DIR / f"{run_id}.yaml"
        path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))


def load_task_summary(run_id: str) -> Optional[dict]:
    """
    Load just summary (handles both single-file and directory formats).

    For single file: extracts run info and basis count
    For directory: loads summary.yaml
    """
    _ensure_dirs()

    # Check directory format first
    dir_path = RESULTS_DIR / run_id
    if dir_path.is_dir():
        summary_path = dir_path / "summary.yaml"
        if summary_path.exists():
            return yaml.safe_load(summary_path.read_text())
        return None

    # Check single file format
    file_path = RESULTS_DIR / f"{run_id}.yaml"
    if file_path.exists():
        data = yaml.safe_load(file_path.read_text())
        run_info = data.get("run", {})
        basis = data.get("basis", [])
        output = data.get("output", {})
        return {
            "run_id": run_info.get("run_id", run_id),
            "status": run_info.get("status", "completed"),
            "completed_at": run_info.get("completed_at"),
            "has_basis": bool(basis),
            "basis_count": len(basis) if isinstance(basis, list) else 0,
            "output_keys": list(output.keys()) if isinstance(output, dict) else [],
        }
    return None


def load_task_output(run_id: str) -> Optional[dict]:
    """
    Load full output object.

    For single file: returns data.get('output')
    For directory: loads output.yaml
    """
    _ensure_dirs()

    # Check directory format first
    dir_path = RESULTS_DIR / run_id
    if dir_path.is_dir():
        output_path = dir_path / "output.yaml"
        if output_path.exists():
            return yaml.safe_load(output_path.read_text())
        return None

    # Check single file format
    file_path = RESULTS_DIR / f"{run_id}.yaml"
    if file_path.exists():
        data = yaml.safe_load(file_path.read_text())
        return data.get("output")
    return None


def load_task_basis(run_id: str) -> Optional[list]:
    """
    Load basis array (citations).

    For single file: returns data.get('basis')
    For directory: loads basis.yaml
    """
    _ensure_dirs()

    # Check directory format first
    dir_path = RESULTS_DIR / run_id
    if dir_path.is_dir():
        basis_path = dir_path / "basis.yaml"
        if basis_path.exists():
            return yaml.safe_load(basis_path.read_text())
        return None

    # Check single file format
    file_path = RESULTS_DIR / f"{run_id}.yaml"
    if file_path.exists():
        data = yaml.safe_load(file_path.read_text())
        return data.get("basis")
    return None


def search_task_basis(run_id: str, query: str) -> list[dict]:
    """
    Search basis items by query (case-insensitive substring match).

    Searches in field, url, reasoning, and citation excerpts.
    Returns list of matching basis items (subset of fields for readability).
    """
    basis = load_task_basis(run_id)
    if not basis:
        return []

    query_lower = query.lower()
    matches = []

    for item in basis:
        try:
            field = str(item.get("field", "")).lower()
            reasoning = str(item.get("reasoning", "")).lower()

            # Check citations
            citations = item.get("citations", [])
            citation_text = ""
            for citation in citations:
                citation_text += str(citation.get("url", "")).lower() + " "
                for excerpt in citation.get("excerpts", []):
                    citation_text += str(excerpt).lower() + " "

            if query_lower in field or query_lower in reasoning or query_lower in citation_text:
                matches.append({
                    "field": item.get("field"),
                    "confidence": item.get("confidence"),
                    "reasoning": item.get("reasoning", "")[:200] if item.get("reasoning") else None,
                    "citation_count": len(citations),
                })
        except Exception:
            pass

    return matches


def parallel_task_create(
    input: str,
    processor: str = "base",
    task_spec: Optional[dict] = None,
    auto_schema: bool = False,
    metadata: Optional[dict] = None,
    source_policy: Optional[dict] = None,
    project: Optional[str] = None,
) -> dict:
    """
    Create a new Task API run for deep research.

    Args:
        input: Task input (question or context for research)
        processor: Processing tier - lite/base/core/core2x/pro/ultra/ultra2x/ultra4x/ultra8x
        task_spec: Optional output schema specification (ignored if auto_schema=True)
        auto_schema: If True, let API auto-generate schema (produces large JSON with basis)
        metadata: Optional user metadata dict
        source_policy: Optional domain preferences dict
        project: Optional project name for filtering/grouping results

    Returns:
        dict with run_id, status, processor, created_at, or error
    """
    api_key = _get_api_key()
    if not api_key:
        return {"error": "PARALLEL_API_KEY not set in environment"}

    if processor not in VALID_PROCESSORS:
        return {"error": f"Invalid processor: {processor}. Valid: {VALID_PROCESSORS}"}

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
    }

    payload: dict[str, Any] = {
        "input": input,
        "processor": processor,
    }

    # Only include task_spec if not using auto_schema
    if not auto_schema and task_spec:
        payload["task_spec"] = task_spec

    if metadata:
        payload["metadata"] = metadata

    if source_policy:
        payload["source_policy"] = source_policy

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(PARALLEL_API_BASE, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()

            run_id = result.get("run_id")
            if run_id:
                # Save pending task for resume capability
                pending_data = {
                    "run_id": run_id,
                    "pilot_run_id": os.environ.get("PILOT_RUN_ID"),
                    "input": input,
                    "processor": processor,
                    "auto_schema": auto_schema,
                    "created_at": datetime.now().isoformat(),
                    "status": result.get("status", "queued"),
                }
                if project:
                    pending_data["project"] = project
                _save_pending(run_id, pending_data)

                # Write progress file for unified status interface
                try:
                    _write_parallel_progress(
                        run_id=run_id,
                        status=result.get("status", "queued"),
                        input_text=input,
                        processor=processor,
                        project=project,
                    )
                except Exception:
                    pass  # Progress tracking is optional, don't fail the task

            return result

    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except httpx.RequestError as e:
        return {"error": f"Request failed: {str(e)}"}


def parallel_task_status(run_id: str) -> dict:
    """
    Check status of a Task API run without blocking.

    Args:
        run_id: Task run ID to check

    Returns:
        dict with run_id, status, is_active, processor, etc., or error
    """
    api_key = _get_api_key()
    if not api_key:
        return {"error": "PARALLEL_API_KEY not set in environment"}

    headers = {
        "x-api-key": api_key,
    }

    url = f"{PARALLEL_API_BASE}/{run_id}"

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            result = response.json()

            # Update progress file with current status
            status = result.get("status", "")
            if status:
                try:
                    _update_parallel_progress(run_id, status)
                except Exception:
                    pass  # Progress tracking is optional

            return result

    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except httpx.RequestError as e:
        return {"error": f"Request failed: {str(e)}"}


def parallel_task_result(
    run_id: str,
    wait: bool = True,
    timeout: int = 1800,
) -> dict:
    """
    Get Task API run result.

    Args:
        run_id: Task run ID to get results for
        wait: If True, block until complete (default True)
        timeout: Max wait time in seconds (default 1800 = 30 min)

    Returns:
        dict with run info, output, basis (citations), or error/status if not ready
    """
    api_key = _get_api_key()
    if not api_key:
        return {"error": "PARALLEL_API_KEY not set in environment"}

    headers = {
        "x-api-key": api_key,
    }

    # Load pending data to get project for result saving
    pending_data = _load_pending(run_id)
    project = pending_data.get("project") if pending_data else None

    if not wait:
        # Just check current status
        status = parallel_task_status(run_id)
        if "error" in status:
            return status

        if status.get("status") == "completed":
            # Fetch full result
            url = f"{PARALLEL_API_BASE}/{run_id}/result"
            try:
                with httpx.Client(timeout=60.0) as client:
                    response = client.get(url, headers=headers)
                    response.raise_for_status()
                    result = response.json()

                    # Save result and remove pending
                    _save_result(run_id, result, project=project)
                    _remove_pending(run_id)

                    # Mark progress as completed
                    try:
                        output = result.get("output", {})
                        summary = str(output)[:200] if output else "Completed"
                        mark_completed(project or DEFAULT_PARALLEL_PROJECT, run_id, summary)
                    except Exception:
                        pass  # Progress tracking is optional

                    return result
            except httpx.HTTPStatusError as e:
                return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
            except httpx.RequestError as e:
                return {"error": f"Request failed: {str(e)}"}
        else:
            return {"status": status.get("status"), "is_active": status.get("is_active", True), "message": "Task not complete yet"}

    # Wait mode: use the blocking /result endpoint with very long timeout
    url = f"{PARALLEL_API_BASE}/{run_id}/result"

    try:
        # Use the full timeout - this endpoint blocks until task completes
        with httpx.Client(timeout=float(timeout)) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            result = response.json()

            # Save result and remove pending
            _save_result(run_id, result, project=project)
            _remove_pending(run_id)

            # Mark progress as completed
            try:
                output = result.get("output", {})
                summary = str(output)[:200] if output else "Completed"
                mark_completed(project or DEFAULT_PARALLEL_PROJECT, run_id, summary)
            except Exception:
                pass  # Progress tracking is optional

            return result

    except httpx.TimeoutException:
        return {"error": f"Timeout after {timeout}s. Task may still be running. Use parallel_task_status to check."}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except httpx.RequestError as e:
        return {"error": f"Request failed: {str(e)}"}


def list_pending_tasks() -> list[dict]:
    """
    List all pending tasks that can be resumed.

    Returns:
        List of pending task dicts with run_id, input, processor, created_at, status
    """
    _ensure_dirs()
    pending = []
    for path in PENDING_DIR.glob("*.yaml"):
        try:
            data = yaml.safe_load(path.read_text())
            pending.append(data)
        except Exception:
            pass
    return sorted(pending, key=lambda x: x.get("created_at", ""), reverse=True)


def list_completed_results(project: Optional[str] = None) -> list[dict]:
    """
    List all completed task results with rich summaries.

    Args:
        project: Optional project name prefix to filter by. If provided, only
                 returns results where project field starts with this prefix.
                 Existing results without project field are included when
                 project is None (backward compatible).

    Returns:
        List of result summaries with:
        - run_id
        - completed_at (if available)
        - has_basis (bool)
        - basis_count (int)
        - output_keys (list of top-level keys in output)
        - path (file or directory path)
        - format ('file' or 'directory')
        - project (if set)
    """
    _ensure_dirs()
    results = []

    # Check for single yaml files (old format)
    for path in RESULTS_DIR.glob("*.yaml"):
        try:
            data = yaml.safe_load(path.read_text())
            run_info = data.get("run", {})
            basis = data.get("basis", [])
            output = data.get("output", {})
            result_project = data.get("project")
            result_entry = {
                "run_id": run_info.get("run_id") or path.stem,
                "completed_at": run_info.get("completed_at"),
                "has_basis": bool(basis),
                "basis_count": len(basis) if isinstance(basis, list) else 0,
                "output_keys": list(output.keys()) if isinstance(output, dict) else [],
                "path": str(path),
                "format": "file",
            }
            if result_project:
                result_entry["project"] = result_project
            results.append(result_entry)
        except Exception:
            pass

    # Check for directories (new format)
    for dir_path in RESULTS_DIR.iterdir():
        if dir_path.is_dir():
            summary_path = dir_path / "summary.yaml"
            if summary_path.exists():
                try:
                    summary = yaml.safe_load(summary_path.read_text())
                    summary["path"] = str(dir_path)
                    summary["format"] = "directory"
                    results.append(summary)
                except Exception:
                    pass

    # Filter by project prefix if specified
    if project:
        results = [
            r for r in results
            if r.get("project") and r["project"].startswith(project)
        ]

    # Sort by completed_at (most recent first), handling None values
    return sorted(results, key=lambda x: x.get("completed_at") or "", reverse=True)


# Convenience wrappers for common use cases

def parallel_task_quick(
    query: str,
    processor: str = "base",
    project: Optional[str] = None,
) -> dict:
    """
    Quick task: create and wait for result in one call.

    Args:
        query: Research query/question
        processor: Processing tier (default: base)
        project: Optional project name for filtering/grouping results

    Returns:
        Task result dict
    """
    create_result = parallel_task_create(
        query, processor=processor, auto_schema=True, project=project
    )
    if "error" in create_result:
        return create_result

    run_id = create_result.get("run_id")
    if not run_id:
        return {"error": "No run_id returned from create"}

    return parallel_task_result(run_id, wait=True)


def parallel_task_deep(
    query: str,
    processor: str = "ultra",
    project: Optional[str] = None,
) -> dict:
    """
    Deep research task with auto schema and ultra processor.

    Args:
        query: Research query/question
        processor: Processing tier (default: ultra for deep research)
        project: Optional project name for filtering/grouping results

    Returns:
        Task result dict with extensive basis/citations
    """
    return parallel_task_quick(query, processor=processor, project=project)


if __name__ == "__main__":
    import json
    from dotenv import load_dotenv

    load_dotenv()

    # Test creating a task
    print("Creating task...")
    result = parallel_task_create(
        "What is the founding date of Anthropic?",
        processor="lite",
        auto_schema=True
    )
    print(json.dumps(result, indent=2))

    if "run_id" in result:
        run_id = result["run_id"]
        print(f"\nChecking status of {run_id}...")
        status = parallel_task_status(run_id)
        print(json.dumps(status, indent=2))
