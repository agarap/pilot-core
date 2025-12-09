"""
Benchmark execution with resume capability.

This module handles running benchmarks against Parallel.ai and comparison systems.
Supports:
- Running individual questions or full benchmarks
- Resume from interruption
- Progress tracking and state persistence
- Multiple processor tiers

Usage:
    from pilot_core.benchmark.runner import (
        run_benchmark,
        run_question_parallel,
        resume_benchmark,
    )

    # Run full benchmark
    result = run_benchmark(benchmark, system="parallel", processor="base")

    # Resume interrupted benchmark
    result = resume_benchmark(customer, result_id)
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

import yaml

from . import (
    Benchmark,
    BenchmarkQuestion,
    BenchmarkResult,
    BenchmarkStatus,
    QuestionAnswer,
    QuestionCategory,
    BENCHMARKS_DIR,
)

# Import Parallel API tools
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from pilot_tools.parallel_task import parallel_task_quick, parallel_task_create, parallel_task_result, parallel_task_status
from pilot_tools.web_search import web_search
from pilot_tools.web_fetch import web_fetch


# Progress callback type
ProgressCallback = Callable[[int, int, str], None]


def run_question_parallel(
    question: BenchmarkQuestion,
    processor: str = "base",
    timeout: int = 300,
) -> QuestionAnswer:
    """
    Run a single question against Parallel.ai APIs.

    Chooses the appropriate API based on question category:
    - SEARCH: Uses web_search
    - ENRICHMENT: Uses web_search + web_fetch
    - RESEARCH: Uses parallel_task

    Args:
        question: BenchmarkQuestion to run
        processor: Parallel processor tier for task API
        timeout: Timeout in seconds

    Returns:
        QuestionAnswer with result
    """
    start_time = time.time()

    try:
        if question.category == QuestionCategory.SEARCH:
            answer = _run_search_question(question)
        elif question.category == QuestionCategory.ENRICHMENT:
            answer = _run_enrichment_question(question)
        else:  # RESEARCH
            answer = _run_research_question(question, processor, timeout)

        answer.latency_ms = int((time.time() - start_time) * 1000)
        return answer

    except Exception as e:
        return QuestionAnswer(
            question_id=question.id,
            answer="",
            error=str(e),
            latency_ms=int((time.time() - start_time) * 1000),
        )


def _run_search_question(question: BenchmarkQuestion) -> QuestionAnswer:
    """Run a search-category question using web_search."""
    result = web_search(
        objective=question.text,
        max_results=10,
    )

    if "error" in result:
        return QuestionAnswer(
            question_id=question.id,
            answer="",
            raw_response=result,
            error=result["error"],
        )

    # Extract answer from search results
    results = result.get("results", [])
    sources = [r.get("url", "") for r in results if r.get("url")]

    # Build answer from excerpts
    answer_parts = []
    for r in results[:5]:  # Top 5 results
        title = r.get("title", "")
        excerpts = r.get("excerpts", [])
        if title:
            answer_parts.append(f"**{title}**")
        for excerpt in excerpts[:2]:  # First 2 excerpts per result
            answer_parts.append(f"- {excerpt}")

    answer = "\n".join(answer_parts) if answer_parts else "No results found"

    return QuestionAnswer(
        question_id=question.id,
        answer=answer,
        raw_response=result,
        sources=sources,
    )


def _run_enrichment_question(question: BenchmarkQuestion) -> QuestionAnswer:
    """Run an enrichment-category question using search + fetch."""
    # First, search for relevant URLs
    search_result = web_search(
        objective=question.text,
        max_results=5,
    )

    if "error" in search_result:
        return QuestionAnswer(
            question_id=question.id,
            answer="",
            raw_response=search_result,
            error=search_result["error"],
        )

    # Extract URLs to fetch
    results = search_result.get("results", [])
    urls = [r.get("url") for r in results if r.get("url")][:3]  # Top 3

    if not urls:
        return QuestionAnswer(
            question_id=question.id,
            answer="No relevant sources found",
            raw_response=search_result,
            sources=[],
        )

    # Fetch content from URLs
    fetch_result = web_fetch(
        urls=urls,
        objective=question.text,
        excerpts=True,
    )

    if "error" in fetch_result:
        # Fall back to search results only
        answer = _build_answer_from_search(search_result)
        return QuestionAnswer(
            question_id=question.id,
            answer=answer,
            raw_response={"search": search_result, "fetch_error": fetch_result["error"]},
            sources=urls,
        )

    # Combine results
    combined = {"search": search_result, "fetch": fetch_result}
    answer = _build_answer_from_fetch(fetch_result)

    return QuestionAnswer(
        question_id=question.id,
        answer=answer,
        raw_response=combined,
        sources=urls,
    )


def _run_research_question(
    question: BenchmarkQuestion,
    processor: str = "base",
    timeout: int = 300,
) -> QuestionAnswer:
    """Run a research-category question using parallel_task."""
    # Build research query with context
    query = question.text
    if question.context:
        query = f"{question.context}\n\n{question.text}"

    result = parallel_task_quick(query, processor=processor)

    if "error" in result:
        return QuestionAnswer(
            question_id=question.id,
            answer="",
            raw_response=result,
            error=result["error"],
        )

    # Extract answer from task output
    output = result.get("output", {})
    basis = result.get("basis", [])

    # Build answer
    if isinstance(output, str):
        answer = output
    elif isinstance(output, dict):
        # Try to extract main answer
        answer = _extract_answer_from_output(output)
    else:
        answer = str(output)

    # Extract sources from basis
    sources = []
    for item in basis[:10]:  # First 10 basis items
        citations = item.get("citations", [])
        for citation in citations:
            url = citation.get("url")
            if url and url not in sources:
                sources.append(url)

    return QuestionAnswer(
        question_id=question.id,
        answer=answer,
        raw_response=result,
        sources=sources[:20],  # Limit to 20 sources
    )


def _build_answer_from_search(search_result: dict) -> str:
    """Build answer text from search results."""
    results = search_result.get("results", [])
    parts = []

    for r in results[:5]:
        title = r.get("title", "")
        excerpts = r.get("excerpts", [])

        if title:
            parts.append(f"**{title}**")
        for excerpt in excerpts[:2]:
            parts.append(f"- {excerpt}")

    return "\n".join(parts) if parts else "No results found"


def _build_answer_from_fetch(fetch_result: dict) -> str:
    """Build answer text from fetch results."""
    results = fetch_result.get("results", [])
    parts = []

    for r in results:
        title = r.get("title", "")
        excerpts = r.get("excerpts", [])

        if title:
            parts.append(f"**{title}**")
        for excerpt in excerpts[:3]:
            parts.append(f"- {excerpt}")

    return "\n".join(parts) if parts else "No content extracted"


def _extract_answer_from_output(output: dict) -> str:
    """Extract main answer from task output dict."""
    # Try common keys
    for key in ["answer", "summary", "result", "response", "conclusion"]:
        if key in output:
            val = output[key]
            if isinstance(val, str):
                return val
            elif isinstance(val, dict):
                return json.dumps(val, indent=2)
            elif isinstance(val, list):
                return "\n".join(str(item) for item in val)

    # Fall back to full output
    return json.dumps(output, indent=2)


def run_benchmark(
    benchmark: Benchmark,
    system: str = "parallel",
    processor: str = "base",
    progress_callback: Optional[ProgressCallback] = None,
    save_interval: int = 5,
) -> BenchmarkResult:
    """
    Run a full benchmark against a system.

    Args:
        benchmark: Benchmark to run
        system: System identifier ("parallel" or comparison system name)
        processor: Parallel processor tier
        progress_callback: Optional callback(current, total, status)
        save_interval: Save progress every N questions

    Returns:
        BenchmarkResult with all answers
    """
    result = BenchmarkResult(
        id=BenchmarkResult.generate_id(system),
        benchmark_id=benchmark.id,
        system=system,
        answers=[],
        processor=processor,
        config={"system": system, "processor": processor},
    )

    total = len(benchmark.questions)

    for i, question in enumerate(benchmark.questions):
        if progress_callback:
            progress_callback(i, total, f"Running question {i+1}/{total}")

        # Run question
        answer = run_question_parallel(question, processor=processor)
        result.answers.append(answer)

        # Update counts
        if answer.error:
            result.error_count += 1
        else:
            result.success_count += 1

        # Save progress periodically
        if (i + 1) % save_interval == 0:
            _save_progress(result, benchmark.customer)

    # Complete and save
    result.complete()
    result.save(benchmark.customer)

    return result


def resume_benchmark(
    customer: str,
    result_id: str,
    benchmark: Optional[Benchmark] = None,
    processor: Optional[str] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> BenchmarkResult:
    """
    Resume an interrupted benchmark run.

    Args:
        customer: Customer name
        result_id: Result ID to resume
        benchmark: Optional Benchmark (loaded if not provided)
        processor: Optional processor override
        progress_callback: Optional callback(current, total, status)

    Returns:
        Completed BenchmarkResult
    """
    # Load existing result
    result = BenchmarkResult.load(customer, result_id)

    if result.status == BenchmarkStatus.COMPLETED:
        return result  # Already done

    # Load benchmark if needed
    if not benchmark:
        benchmark = Benchmark.load(customer, result.benchmark_id)

    # Determine which questions still need answers
    answered_ids = result.answered_question_ids()
    remaining = [q for q in benchmark.questions if q.id not in answered_ids]

    if not remaining:
        result.complete()
        result.save(customer)
        return result

    # Use existing or overridden processor
    proc = processor or result.processor

    total = len(benchmark.questions)
    current = len(answered_ids)

    for i, question in enumerate(remaining):
        if progress_callback:
            progress_callback(current + i, total, f"Resuming: {current + i + 1}/{total}")

        answer = run_question_parallel(question, processor=proc)
        result.answers.append(answer)

        if answer.error:
            result.error_count += 1
        else:
            result.success_count += 1

        # Save progress every 5 questions
        if (i + 1) % 5 == 0:
            _save_progress(result, customer)

    result.complete()
    result.save(customer)

    return result


def _save_progress(result: BenchmarkResult, customer: str) -> None:
    """Save result progress to disk."""
    result.status = BenchmarkStatus.IN_PROGRESS
    result.save(customer)


def list_incomplete_results(customer: str) -> list[dict]:
    """
    List incomplete benchmark results that can be resumed.

    Args:
        customer: Customer name

    Returns:
        List of result summaries with id, benchmark_id, answered_count, total_count
    """
    from . import list_results, list_benchmarks

    incomplete = []
    result_ids = list_results(customer)

    for result_id in result_ids:
        try:
            result = BenchmarkResult.load(customer, result_id)
            if result.status != BenchmarkStatus.COMPLETED:
                # Load benchmark to get total count
                try:
                    benchmark = Benchmark.load(customer, result.benchmark_id)
                    total = len(benchmark.questions)
                except Exception:
                    total = -1

                incomplete.append({
                    "result_id": result_id,
                    "benchmark_id": result.benchmark_id,
                    "system": result.system,
                    "answered_count": len(result.answers),
                    "total_count": total,
                    "status": result.status.value,
                    "started_at": result.started_at,
                })
        except Exception:
            pass

    return incomplete


def run_benchmark_async(
    benchmark: Benchmark,
    system: str = "parallel",
    processor: str = "base",
) -> str:
    """
    Start a benchmark run asynchronously (for long-running benchmarks).

    Returns the result ID immediately. Use resume_benchmark to check progress.

    Args:
        benchmark: Benchmark to run
        system: System identifier
        processor: Processor tier

    Returns:
        Result ID (use resume_benchmark to continue)
    """
    # Create result and save initial state
    result = BenchmarkResult(
        id=BenchmarkResult.generate_id(system),
        benchmark_id=benchmark.id,
        system=system,
        answers=[],
        processor=processor,
        config={"system": system, "processor": processor, "async": True},
    )

    result.save(benchmark.customer)

    return result.id


def get_benchmark_progress(customer: str, result_id: str) -> dict:
    """
    Get progress of a benchmark run.

    Args:
        customer: Customer name
        result_id: Result ID

    Returns:
        Progress dict with status, answered, total, percent_complete
    """
    try:
        result = BenchmarkResult.load(customer, result_id)
        benchmark = Benchmark.load(customer, result.benchmark_id)

        answered = len(result.answers)
        total = len(benchmark.questions)
        percent = (answered / total * 100) if total > 0 else 0

        return {
            "result_id": result_id,
            "status": result.status.value,
            "answered": answered,
            "total": total,
            "percent_complete": round(percent, 1),
            "success_count": result.success_count,
            "error_count": result.error_count,
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python -m lib.benchmark.runner <customer> <benchmark_id> [processor]")
        print("       python -m lib.benchmark.runner --resume <customer> <result_id>")
        sys.exit(1)

    if sys.argv[1] == "--resume":
        customer = sys.argv[2]
        result_id = sys.argv[3]

        def progress(current, total, status):
            print(f"[{current}/{total}] {status}")

        result = resume_benchmark(customer, result_id, progress_callback=progress)
        print(f"Completed: {result.success_count} success, {result.error_count} errors")

    else:
        customer = sys.argv[1]
        benchmark_id = sys.argv[2]
        processor = sys.argv[3] if len(sys.argv) > 3 else "base"

        benchmark = Benchmark.load(customer, benchmark_id)

        def progress(current, total, status):
            print(f"[{current}/{total}] {status}")

        result = run_benchmark(benchmark, processor=processor, progress_callback=progress)
        print(f"Result ID: {result.id}")
        print(f"Completed: {result.success_count} success, {result.error_count} errors")
