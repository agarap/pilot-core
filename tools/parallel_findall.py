"""
tool: parallel_findall
description: Web-scale entity discovery using Parallel.ai FindAll API with async support and large result handling
parameters:
  For parallel_findall_create:
    objective: Natural language objective for entity discovery
    entity_type: Type of entities to find (companies, people, products, etc.)
    match_conditions: List of dicts with 'name' and 'description' for filtering
    generator: Generator tier (preview, base, core, pro)
    match_limit: Max matches to return (5-1000, default 50)
    exclude_list: Optional list of entities to exclude
    metadata: Optional user metadata dict
    project: Optional project name for filtering/grouping results
  For parallel_findall_status:
    findall_id: FindAll run ID to check
  For parallel_findall_result:
    findall_id: FindAll run ID to get results for
    wait: If True, block until complete (default True)
    timeout: Max wait time in seconds (default 3600 = 1 hour)
  For list_completed_findalls:
    project: Optional project name prefix to filter by
returns: Dict with findall_id, status, candidates (with basis/citations), or error
"""

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml


PARALLEL_API_BASE = "https://api.parallel.ai/v1beta/findall/runs"
PARALLEL_BETA_HEADER = "findall-2025-09-15"

# Generator tiers: preview ($0.10 fixed), base ($0.25 fixed + $0.03/match),
# core ($2 fixed + $0.15/match), pro ($10 fixed + $1/match)
VALID_GENERATORS = ["preview", "base", "core", "pro"]

# Data directories for persistence
PENDING_DIR = Path("data/parallel_findall/pending")
RESULTS_DIR = Path("data/parallel_findall/results")


def _ensure_dirs():
    """Ensure persistence directories exist."""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _get_api_key() -> Optional[str]:
    """Get API key from environment, loading .env if needed."""
    from dotenv import load_dotenv
    load_dotenv()
    return os.environ.get("PARALLEL_API_KEY")


def _save_pending(findall_id: str, data: dict):
    """Save pending findall info for resume capability."""
    _ensure_dirs()
    path = PENDING_DIR / f"{findall_id}.yaml"
    path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))


def _load_pending(findall_id: str) -> Optional[dict]:
    """Load pending findall info if exists."""
    path = PENDING_DIR / f"{findall_id}.yaml"
    if path.exists():
        return yaml.safe_load(path.read_text())
    return None


def _remove_pending(findall_id: str):
    """Remove pending file after findall completes."""
    path = PENDING_DIR / f"{findall_id}.yaml"
    if path.exists():
        path.unlink()


def _save_result(findall_id: str, data: dict, project: Optional[str] = None):
    """
    Save findall result with individual candidate files for searchability.

    Creates:
    - data/parallel_findall/results/{findall_id}/summary.yaml (overview)
    - data/parallel_findall/results/{findall_id}/candidates/{candidate_id}.yaml (each candidate)

    Args:
        findall_id: FindAll run ID
        data: Result data from API
        project: Optional project name for filtering/grouping
    """
    _ensure_dirs()
    result_dir = RESULTS_DIR / findall_id
    candidates_dir = result_dir / "candidates"
    result_dir.mkdir(parents=True, exist_ok=True)
    candidates_dir.mkdir(parents=True, exist_ok=True)

    # Extract candidates
    candidates = data.get("candidates", [])

    # Save summary (without full candidate data)
    summary = {
        "findall_id": findall_id,
        "status": data.get("status"),
        "generator": data.get("generator"),
        "created_at": data.get("created_at"),
        "completed_at": datetime.now().isoformat(),
        "total_candidates": len(candidates),
        "matched_count": sum(1 for c in candidates if c.get("match_status") == "matched"),
        "candidate_ids": [c.get("candidate_id") for c in candidates],
    }
    if project:
        summary["project"] = project
    summary_path = result_dir / "summary.yaml"
    summary_path.write_text(yaml.dump(summary, default_flow_style=False, allow_unicode=True))

    # Save individual candidates
    for candidate in candidates:
        candidate_id = candidate.get("candidate_id", "unknown")
        candidate_path = candidates_dir / f"{candidate_id}.yaml"
        candidate_path.write_text(yaml.dump(candidate, default_flow_style=False, allow_unicode=True))

    return str(result_dir)


def parallel_findall_create(
    objective: str,
    entity_type: str,
    match_conditions: list[dict],
    generator: str = "base",
    match_limit: int = 50,
    exclude_list: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
    project: Optional[str] = None,
) -> dict:
    """
    Create a new FindAll API run for web-scale entity discovery.

    Args:
        objective: Natural language objective (e.g., "Find AI companies that raised Series A")
        entity_type: Type of entities to find (companies, people, products, etc.)
        match_conditions: List of dicts with 'name' and 'description' keys for filtering
        generator: Generator tier - preview/base/core/pro (default: base)
        match_limit: Max matches to return, 5-1000 (default: 50)
        exclude_list: Optional list of entity names to exclude
        metadata: Optional user metadata dict
        project: Optional project name for filtering/grouping results

    Returns:
        dict with findall_id, status, generator, etc., or error
    """
    api_key = _get_api_key()
    if not api_key:
        return {"error": "PARALLEL_API_KEY not set in environment"}

    if generator not in VALID_GENERATORS:
        return {"error": f"Invalid generator: {generator}. Valid: {VALID_GENERATORS}"}

    if not match_conditions:
        return {"error": "match_conditions is required (list of dicts with 'name' and 'description')"}

    if match_limit < 5 or match_limit > 1000:
        return {"error": "match_limit must be between 5 and 1000"}

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "parallel-beta": PARALLEL_BETA_HEADER,
    }

    payload: dict[str, Any] = {
        "objective": objective,
        "entity_type": entity_type,
        "match_conditions": match_conditions,
        "generator": generator,
        "match_limit": match_limit,
    }

    if exclude_list:
        payload["exclude_list"] = exclude_list

    if metadata:
        payload["metadata"] = metadata

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(PARALLEL_API_BASE, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()

            findall_id = result.get("findall_id")
            if findall_id:
                # Save pending findall for resume capability
                pending_data = {
                    "findall_id": findall_id,
                    "pilot_run_id": os.environ.get("PILOT_RUN_ID"),
                    "objective": objective,
                    "entity_type": entity_type,
                    "match_conditions": match_conditions,
                    "generator": generator,
                    "match_limit": match_limit,
                    "created_at": datetime.now().isoformat(),
                    "status": "created",
                }
                if project:
                    pending_data["project"] = project
                _save_pending(findall_id, pending_data)

            return result

    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except httpx.RequestError as e:
        return {"error": f"Request failed: {str(e)}"}


def parallel_findall_status(findall_id: str) -> dict:
    """
    Check status of a FindAll API run without blocking.

    Args:
        findall_id: FindAll run ID to check

    Returns:
        dict with findall_id, status, metrics (generated/matched counts), or error
    """
    api_key = _get_api_key()
    if not api_key:
        return {"error": "PARALLEL_API_KEY not set in environment"}

    headers = {
        "x-api-key": api_key,
        "parallel-beta": PARALLEL_BETA_HEADER,
    }

    url = f"{PARALLEL_API_BASE}/{findall_id}"

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except httpx.RequestError as e:
        return {"error": f"Request failed: {str(e)}"}


def parallel_findall_result(
    findall_id: str,
    wait: bool = True,
    timeout: int = 3600,
    poll_interval: int = 30,
) -> dict:
    """
    Get FindAll API run result.

    Args:
        findall_id: FindAll run ID to get results for
        wait: If True, poll until complete (default True)
        timeout: Max wait time in seconds (default 3600 = 1 hour)
        poll_interval: Seconds between status checks when waiting (default 30)

    Returns:
        dict with findall_id, status, candidates (with basis), saved_path, or error
    """
    api_key = _get_api_key()
    if not api_key:
        return {"error": "PARALLEL_API_KEY not set in environment"}

    headers = {
        "x-api-key": api_key,
        "parallel-beta": PARALLEL_BETA_HEADER,
    }

    result_url = f"{PARALLEL_API_BASE}/{findall_id}/result"

    # Load pending data to get project for result saving
    pending_data = _load_pending(findall_id)
    project = pending_data.get("project") if pending_data else None

    def fetch_result():
        """Fetch the full result."""
        with httpx.Client(timeout=120.0) as client:
            response = client.get(result_url, headers=headers)
            response.raise_for_status()
            return response.json()

    if not wait:
        # Just check current status
        status = parallel_findall_status(findall_id)
        if "error" in status:
            return status

        status_info = status.get("status", {})
        status_str = status_info.get("status") if isinstance(status_info, dict) else status_info

        if status_str == "completed":
            try:
                result = fetch_result()
                saved_path = _save_result(findall_id, result, project=project)
                _remove_pending(findall_id)
                result["saved_path"] = saved_path
                return result
            except httpx.HTTPStatusError as e:
                return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
            except httpx.RequestError as e:
                return {"error": f"Request failed: {str(e)}"}
        else:
            metrics = status.get("status", {}).get("metrics", {}) if isinstance(status.get("status"), dict) else {}
            return {
                "status": status_str,
                "is_active": status_info.get("is_active", True) if isinstance(status_info, dict) else True,
                "metrics": metrics,
                "message": "FindAll not complete yet. Use wait=True or check again later.",
            }

    # Wait mode: poll until complete or timeout
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout:
            return {
                "error": f"Timeout after {timeout}s. FindAll may still be running.",
                "findall_id": findall_id,
                "message": "Use parallel_findall_status to check progress.",
            }

        status = parallel_findall_status(findall_id)
        if "error" in status:
            return status

        status_info = status.get("status", {})
        status_str = status_info.get("status") if isinstance(status_info, dict) else status_info

        if status_str == "completed":
            try:
                result = fetch_result()
                saved_path = _save_result(findall_id, result, project=project)
                _remove_pending(findall_id)
                result["saved_path"] = saved_path
                return result
            except httpx.HTTPStatusError as e:
                return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
            except httpx.RequestError as e:
                return {"error": f"Request failed: {str(e)}"}

        elif status_str == "failed":
            return {"error": "FindAll run failed", "status": status}

        # Still running, wait and poll again
        metrics = status_info.get("metrics", {}) if isinstance(status_info, dict) else {}
        generated = metrics.get("generated_candidates_count", 0)
        matched = metrics.get("matched_candidates_count", 0)

        # Update pending with latest metrics
        pending = _load_pending(findall_id)
        if pending:
            pending["last_check"] = datetime.now().isoformat()
            pending["generated"] = generated
            pending["matched"] = matched
            _save_pending(findall_id, pending)

        time.sleep(poll_interval)


def list_pending_findalls() -> list[dict]:
    """
    List all pending findall runs that can be resumed.

    Returns:
        List of pending findall dicts
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


def list_completed_findalls(project: Optional[str] = None) -> list[dict]:
    """
    List all completed findall results.

    Args:
        project: Optional project name prefix to filter by. If provided, only
                 returns results where project field starts with this prefix.
                 Existing results without project field are included when
                 project is None (backward compatible).

    Returns:
        List of result summaries
    """
    _ensure_dirs()
    results = []
    for result_dir in RESULTS_DIR.iterdir():
        if result_dir.is_dir():
            summary_path = result_dir / "summary.yaml"
            if summary_path.exists():
                try:
                    data = yaml.safe_load(summary_path.read_text())
                    results.append(data)
                except Exception:
                    pass

    # Filter by project prefix if specified
    if project:
        results = [
            r for r in results
            if r.get("project") and r["project"].startswith(project)
        ]

    return sorted(results, key=lambda x: x.get("completed_at", ""), reverse=True)


def load_findall_candidate(findall_id: str, candidate_id: str) -> Optional[dict]:
    """
    Load a specific candidate from a completed findall result.

    Args:
        findall_id: FindAll run ID
        candidate_id: Candidate ID to load

    Returns:
        Candidate dict with full basis/citations, or None if not found
    """
    candidate_path = RESULTS_DIR / findall_id / "candidates" / f"{candidate_id}.yaml"
    if candidate_path.exists():
        return yaml.safe_load(candidate_path.read_text())
    return None


def search_findall_candidates(findall_id: str, query: str) -> list[dict]:
    """
    Search candidates in a completed findall result by name/description.

    Args:
        findall_id: FindAll run ID
        query: Search query (case-insensitive substring match)

    Returns:
        List of matching candidates (summaries, not full data)
    """
    candidates_dir = RESULTS_DIR / findall_id / "candidates"
    if not candidates_dir.exists():
        return []

    query_lower = query.lower()
    matches = []

    for path in candidates_dir.glob("*.yaml"):
        try:
            data = yaml.safe_load(path.read_text())
            name = str(data.get("name", "")).lower()
            desc = str(data.get("description", "")).lower()

            if query_lower in name or query_lower in desc:
                matches.append({
                    "candidate_id": data.get("candidate_id"),
                    "name": data.get("name"),
                    "url": data.get("url"),
                    "match_status": data.get("match_status"),
                })
        except Exception:
            pass

    return matches


# Convenience wrappers for common use cases

def parallel_findall_companies(
    objective: str,
    match_conditions: list[dict],
    generator: str = "base",
    match_limit: int = 50,
    project: Optional[str] = None,
) -> dict:
    """
    Convenience wrapper for finding companies.

    Args:
        objective: What kind of companies to find
        match_conditions: Filtering conditions
        generator: Generator tier (default: base)
        match_limit: Max matches (default: 50)
        project: Optional project name for filtering/grouping results

    Returns:
        Create result with findall_id
    """
    return parallel_findall_create(
        objective=objective,
        entity_type="companies",
        match_conditions=match_conditions,
        generator=generator,
        match_limit=match_limit,
        project=project,
    )


def parallel_findall_people(
    objective: str,
    match_conditions: list[dict],
    generator: str = "base",
    match_limit: int = 50,
    project: Optional[str] = None,
) -> dict:
    """
    Convenience wrapper for finding people.

    Args:
        objective: What kind of people to find
        match_conditions: Filtering conditions
        generator: Generator tier (default: base)
        match_limit: Max matches (default: 50)
        project: Optional project name for filtering/grouping results

    Returns:
        Create result with findall_id
    """
    return parallel_findall_create(
        objective=objective,
        entity_type="people",
        match_conditions=match_conditions,
        generator=generator,
        match_limit=match_limit,
        project=project,
    )


if __name__ == "__main__":
    import json
    from dotenv import load_dotenv

    load_dotenv()

    # Test creating a findall (preview mode is cheap for testing)
    print("Creating findall...")
    result = parallel_findall_create(
        objective="Find AI startups focused on code generation",
        entity_type="companies",
        match_conditions=[
            {"name": "ai_focus", "description": "Company focused on AI/ML"},
            {"name": "code_gen", "description": "Company builds code generation tools"},
        ],
        generator="preview",
        match_limit=10,
    )
    print(json.dumps(result, indent=2))

    if "findall_id" in result:
        findall_id = result["findall_id"]
        print(f"\nChecking status of {findall_id}...")
        status = parallel_findall_status(findall_id)
        print(json.dumps(status, indent=2))
