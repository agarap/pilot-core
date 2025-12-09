"""
CLI helper functions for the benchmark system.

These functions are called by tools/benchmark.py and provide a clean
interface between the CLI tool and the benchmark modules.

Usage:
    from lib.benchmark.cli import (
        create_benchmark_cli,
        run_benchmark_cli,
        evaluate_benchmark_cli,
        benchmark_status_cli,
        list_benchmarks_cli,
        full_benchmark_cli,
    )
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import (
    Benchmark,
    BenchmarkResult,
    Evaluation,
    BenchmarkStatus,
    list_benchmarks,
    list_results,
    list_evaluations,
    list_customers,
    BENCHMARKS_DIR,
)
from .creator import create_benchmark, validate_benchmark, research_customer
from .runner import (
    run_benchmark,
    resume_benchmark,
    list_incomplete_results,
    get_benchmark_progress,
)
from .evaluator import (
    evaluate_benchmark,
    quick_evaluate,
    generate_report,
)


def create_benchmark_cli(
    customer: str,
    use_case: Optional[str] = None,
    processor: str = "base",
    min_questions: int = 30,
    max_questions: int = 70,
    verbose: bool = False,
) -> dict:
    """
    Create a new benchmark for a customer.

    Args:
        customer: Customer name (will create directory under projects/benchmarks/)
        use_case: Optional use case hint to focus question generation
        processor: Parallel processor tier for research (base, core, pro)
        min_questions: Minimum number of questions to generate
        max_questions: Maximum number of questions to generate
        verbose: Print progress updates

    Returns:
        dict with benchmark_id, customer, question_count, validation, path
    """
    try:
        if verbose:
            print(f"Creating benchmark for: {customer}")
            print(f"Use case hint: {use_case or 'none'}")
            print(f"Processor: {processor}")
            print(f"Question range: {min_questions}-{max_questions}")

        benchmark = create_benchmark(
            customer=customer,
            use_case_hint=use_case,
            count_range=(min_questions, max_questions),
            processor=processor,
            save=True,
        )

        is_valid, issues = validate_benchmark(benchmark)

        result = {
            "success": True,
            "benchmark_id": benchmark.id,
            "customer": benchmark.customer,
            "use_case": benchmark.use_case,
            "question_count": len(benchmark.questions),
            "question_distribution": benchmark.question_counts(),
            "validation": {
                "is_valid": is_valid,
                "issues": issues,
            },
            "path": str(BENCHMARKS_DIR / customer / f"{benchmark.id}.yaml"),
            "created_at": benchmark.created_at,
        }

        if verbose:
            print(f"\nBenchmark created: {benchmark.id}")
            print(f"Questions: {len(benchmark.questions)}")
            print(f"Distribution: {benchmark.question_counts()}")
            if not is_valid:
                print(f"Validation issues: {issues}")

        return result

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "customer": customer,
        }


def run_benchmark_cli(
    customer: str,
    benchmark_id: Optional[str] = None,
    result_id: Optional[str] = None,
    system: str = "parallel",
    processor: str = "base",
    verbose: bool = False,
) -> dict:
    """
    Run a benchmark or resume an incomplete run.

    Args:
        customer: Customer name
        benchmark_id: Benchmark ID to run (if starting new)
        result_id: Result ID to resume (if resuming)
        system: System identifier for this run
        processor: Parallel processor tier
        verbose: Print progress updates

    Returns:
        dict with result_id, status, success_count, error_count, path
    """
    try:
        # Set up progress callback if verbose
        progress_cb = None
        if verbose:
            def progress_cb(current, total, status):
                print(f"[{current}/{total}] {status}")

        # Resume existing run
        if result_id:
            if verbose:
                print(f"Resuming run: {result_id}")

            result = resume_benchmark(
                customer=customer,
                result_id=result_id,
                processor=processor,
                progress_callback=progress_cb,
            )
        # Start new run
        elif benchmark_id:
            if verbose:
                print(f"Starting new run for benchmark: {benchmark_id}")

            benchmark = Benchmark.load(customer, benchmark_id)
            result = run_benchmark(
                benchmark=benchmark,
                system=system,
                processor=processor,
                progress_callback=progress_cb,
            )
        else:
            return {
                "success": False,
                "error": "Must provide either benchmark_id or result_id",
            }

        return {
            "success": True,
            "result_id": result.id,
            "benchmark_id": result.benchmark_id,
            "system": result.system,
            "status": result.status.value,
            "success_count": result.success_count,
            "error_count": result.error_count,
            "total_questions": len(result.answers),
            "total_latency_ms": result.total_latency_ms,
            "path": str(BENCHMARKS_DIR / customer / "results" / f"{result.id}.yaml"),
            "completed_at": result.completed_at,
        }

    except FileNotFoundError as e:
        return {
            "success": False,
            "error": f"Not found: {e}",
            "customer": customer,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "customer": customer,
        }


def evaluate_benchmark_cli(
    customer: str,
    result_a_id: str,
    result_b_id: str,
    save_report: bool = True,
    verbose: bool = False,
) -> dict:
    """
    Evaluate two benchmark results side-by-side.

    Args:
        customer: Customer name
        result_a_id: First result ID (typically Parallel)
        result_b_id: Second result ID (comparison system)
        save_report: Whether to save markdown report
        verbose: Print progress updates

    Returns:
        dict with evaluation_id, winner, confidence, scores, report_path
    """
    try:
        if verbose:
            print(f"Evaluating: {result_a_id} vs {result_b_id}")

        evaluation = quick_evaluate(
            customer=customer,
            parallel_result_id=result_a_id,
            comparison_result_id=result_b_id,
            save=True,
        )

        # Generate and save report
        report_path = None
        if save_report:
            parallel_result = BenchmarkResult.load(customer, result_a_id)
            benchmark = Benchmark.load(customer, parallel_result.benchmark_id)
            report = generate_report(evaluation, benchmark)

            report_path = BENCHMARKS_DIR / customer / "evaluations" / f"{evaluation.id}-report.md"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            with open(report_path, "w") as f:
                f.write(report)

            if verbose:
                print(f"\nReport saved: {report_path}")
                print("\n" + "=" * 50)
                print(report[:2000])  # First 2000 chars
                if len(report) > 2000:
                    print(f"\n... (truncated, see full report at {report_path})")

        agg = evaluation.aggregate_scores

        return {
            "success": True,
            "evaluation_id": evaluation.id,
            "benchmark_id": evaluation.benchmark_id,
            "winner": evaluation.winner.value,
            "confidence": evaluation.confidence,
            "parallel_result_id": result_a_id,
            "comparison_result_id": result_b_id,
            "comparison_system": evaluation.comparison_system,
            "scores": {
                "parallel_average": agg.parallel_average,
                "comparison_average": agg.comparison_average,
                "parallel_wins": agg.parallel_wins,
                "comparison_wins": agg.comparison_wins,
                "ties": agg.ties,
                "by_category": agg.by_category,
                "by_difficulty": agg.by_difficulty,
            },
            "strengths_parallel": evaluation.strengths_parallel,
            "strengths_comparison": evaluation.strengths_comparison,
            "evaluation_path": str(BENCHMARKS_DIR / customer / "evaluations" / f"{evaluation.id}.yaml"),
            "report_path": str(report_path) if report_path else None,
            "created_at": evaluation.created_at,
        }

    except FileNotFoundError as e:
        return {
            "success": False,
            "error": f"Not found: {e}",
            "customer": customer,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "customer": customer,
        }


def benchmark_status_cli(
    customer: str,
    benchmark_id: Optional[str] = None,
    result_id: Optional[str] = None,
    evaluation_id: Optional[str] = None,
) -> dict:
    """
    Get status of a benchmark, result, or evaluation.

    Args:
        customer: Customer name
        benchmark_id: Benchmark ID to check
        result_id: Result ID to check
        evaluation_id: Evaluation ID to check

    Returns:
        dict with status information for the requested item
    """
    try:
        if benchmark_id:
            benchmark = Benchmark.load(customer, benchmark_id)
            return {
                "success": True,
                "type": "benchmark",
                "id": benchmark.id,
                "customer": benchmark.customer,
                "use_case": benchmark.use_case,
                "status": benchmark.status.value,
                "question_count": len(benchmark.questions),
                "question_distribution": benchmark.question_counts(),
                "created_at": benchmark.created_at,
                "identified_use_cases": benchmark.identified_use_cases,
                "has_research": bool(benchmark.customer_research),
            }

        elif result_id:
            progress = get_benchmark_progress(customer, result_id)
            if "error" in progress:
                return {
                    "success": False,
                    "error": progress["error"],
                }

            return {
                "success": True,
                "type": "result",
                **progress,
            }

        elif evaluation_id:
            evaluation = Evaluation.load(customer, evaluation_id)
            agg = evaluation.aggregate_scores

            return {
                "success": True,
                "type": "evaluation",
                "id": evaluation.id,
                "benchmark_id": evaluation.benchmark_id,
                "winner": evaluation.winner.value,
                "confidence": evaluation.confidence,
                "parallel_result_id": evaluation.parallel_result_id,
                "comparison_result_id": evaluation.comparison_result_id,
                "comparison_system": evaluation.comparison_system,
                "parallel_average": agg.parallel_average,
                "comparison_average": agg.comparison_average,
                "parallel_wins": agg.parallel_wins,
                "comparison_wins": agg.comparison_wins,
                "ties": agg.ties,
                "questions_scored": len(evaluation.question_scores),
                "created_at": evaluation.created_at,
            }

        else:
            return {
                "success": False,
                "error": "Must provide benchmark_id, result_id, or evaluation_id",
            }

    except FileNotFoundError as e:
        return {
            "success": False,
            "error": f"Not found: {e}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def list_benchmarks_cli(
    customer: Optional[str] = None,
    include_results: bool = True,
    include_evaluations: bool = True,
) -> dict:
    """
    List benchmarks, results, and evaluations.

    Args:
        customer: Customer name (if None, lists all customers)
        include_results: Include result listing
        include_evaluations: Include evaluation listing

    Returns:
        dict with customers, benchmarks, results, evaluations lists
    """
    try:
        result = {
            "success": True,
        }

        if customer:
            # List for specific customer
            result["customer"] = customer
            result["benchmarks"] = list_benchmarks(customer)

            if include_results:
                result["results"] = list_results(customer)
                result["incomplete_results"] = list_incomplete_results(customer)

            if include_evaluations:
                result["evaluations"] = list_evaluations(customer)

        else:
            # List all customers and their counts
            customers = list_customers()
            result["customers"] = []

            for cust in customers:
                cust_data = {
                    "name": cust,
                    "benchmark_count": len(list_benchmarks(cust)),
                }
                if include_results:
                    cust_data["result_count"] = len(list_results(cust))
                if include_evaluations:
                    cust_data["evaluation_count"] = len(list_evaluations(cust))

                result["customers"].append(cust_data)

        return result

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def full_benchmark_cli(
    customer: str,
    use_case: Optional[str] = None,
    processor: str = "base",
    comparison_system: Optional[str] = None,
    min_questions: int = 30,
    max_questions: int = 70,
    verbose: bool = False,
) -> dict:
    """
    Run full benchmark pipeline: create -> run -> (optionally) evaluate.

    Args:
        customer: Customer name
        use_case: Optional use case hint
        processor: Parallel processor tier
        comparison_system: If provided, also run against this system and evaluate
        min_questions: Minimum questions to generate
        max_questions: Maximum questions to generate
        verbose: Print progress updates

    Returns:
        dict with benchmark_id, result_id, evaluation_id (if comparison), final_status
    """
    result = {
        "success": True,
        "customer": customer,
        "stages": {},
    }

    try:
        # Stage 1: Create benchmark
        if verbose:
            print("\n" + "=" * 50)
            print("STAGE 1: Creating benchmark")
            print("=" * 50)

        create_result = create_benchmark_cli(
            customer=customer,
            use_case=use_case,
            processor=processor,
            min_questions=min_questions,
            max_questions=max_questions,
            verbose=verbose,
        )

        result["stages"]["create"] = create_result
        if not create_result.get("success"):
            result["success"] = False
            result["error"] = f"Create failed: {create_result.get('error')}"
            return result

        benchmark_id = create_result["benchmark_id"]
        result["benchmark_id"] = benchmark_id

        # Stage 2: Run against Parallel
        if verbose:
            print("\n" + "=" * 50)
            print("STAGE 2: Running benchmark against Parallel")
            print("=" * 50)

        run_result = run_benchmark_cli(
            customer=customer,
            benchmark_id=benchmark_id,
            system="parallel",
            processor=processor,
            verbose=verbose,
        )

        result["stages"]["run_parallel"] = run_result
        if not run_result.get("success"):
            result["success"] = False
            result["error"] = f"Run failed: {run_result.get('error')}"
            return result

        parallel_result_id = run_result["result_id"]
        result["parallel_result_id"] = parallel_result_id

        # Stage 3 (optional): Run against comparison system
        if comparison_system:
            if verbose:
                print("\n" + "=" * 50)
                print(f"STAGE 3: Running benchmark against {comparison_system}")
                print("=" * 50)

            # Note: Currently the runner only supports Parallel.ai
            # This would need custom implementation for other systems
            comparison_run_result = run_benchmark_cli(
                customer=customer,
                benchmark_id=benchmark_id,
                system=comparison_system,
                processor=processor,
                verbose=verbose,
            )

            result["stages"]["run_comparison"] = comparison_run_result
            if not comparison_run_result.get("success"):
                result["success"] = False
                result["error"] = f"Comparison run failed: {comparison_run_result.get('error')}"
                return result

            comparison_result_id = comparison_run_result["result_id"]
            result["comparison_result_id"] = comparison_result_id

            # Stage 4: Evaluate
            if verbose:
                print("\n" + "=" * 50)
                print("STAGE 4: Evaluating results")
                print("=" * 50)

            eval_result = evaluate_benchmark_cli(
                customer=customer,
                result_a_id=parallel_result_id,
                result_b_id=comparison_result_id,
                save_report=True,
                verbose=verbose,
            )

            result["stages"]["evaluate"] = eval_result
            if not eval_result.get("success"):
                result["success"] = False
                result["error"] = f"Evaluation failed: {eval_result.get('error')}"
                return result

            result["evaluation_id"] = eval_result["evaluation_id"]
            result["winner"] = eval_result["winner"]
            result["confidence"] = eval_result["confidence"]
            result["report_path"] = eval_result.get("report_path")

        # Final summary
        result["final_status"] = "completed"
        if verbose:
            print("\n" + "=" * 50)
            print("PIPELINE COMPLETE")
            print("=" * 50)
            print(f"Benchmark: {benchmark_id}")
            print(f"Parallel Result: {parallel_result_id}")
            if comparison_system:
                print(f"Comparison Result: {comparison_result_id}")
                print(f"Winner: {result.get('winner')} (confidence: {result.get('confidence'):.0%})")

        return result

    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        result["final_status"] = "failed"
        return result
