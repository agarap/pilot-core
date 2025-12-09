"""
tool: benchmark
description: Create and run benchmarks for Parallel.ai customer evaluation
parameters:
  action: Action to perform (create|run|evaluate|status|list|full)
  customer: Customer name (required for most actions)
  benchmark_id: Benchmark ID (for run, status)
  result_id: Result ID (for status, resume)
  result_a_id: First result ID for evaluation (typically Parallel)
  result_b_id: Second result ID for evaluation (comparison system)
  evaluation_id: Evaluation ID (for status)
  use_case: Use case hint for benchmark creation
  processor: Parallel processor tier (lite|base|core|pro|ultra)
  system: System identifier for benchmark run
  comparison_system: Comparison system for full pipeline
  min_questions: Minimum questions for create (default 30)
  max_questions: Maximum questions for create (default 70)
  verbose: Print detailed progress (default false)
returns: Dict with action-specific results
"""

import json
import sys
from typing import Any, Optional

from pilot_core.benchmark.cli import (
    create_benchmark_cli,
    run_benchmark_cli,
    evaluate_benchmark_cli,
    benchmark_status_cli,
    list_benchmarks_cli,
    full_benchmark_cli,
)


def benchmark(
    action: str,
    customer: Optional[str] = None,
    benchmark_id: Optional[str] = None,
    result_id: Optional[str] = None,
    result_a_id: Optional[str] = None,
    result_b_id: Optional[str] = None,
    evaluation_id: Optional[str] = None,
    use_case: Optional[str] = None,
    processor: str = "base",
    system: str = "parallel",
    comparison_system: Optional[str] = None,
    min_questions: int = 30,
    max_questions: int = 70,
    verbose: bool = False,
) -> dict[str, Any]:
    """
    Unified benchmark tool for creating, running, and evaluating benchmarks.

    Actions:
        create: Create a new benchmark from customer research
        run: Run a benchmark against Parallel.ai (or resume an incomplete run)
        evaluate: Compare two benchmark results side-by-side
        status: Check status of benchmark, result, or evaluation
        list: List benchmarks, results, and evaluations
        full: Run complete pipeline (create -> run -> evaluate)

    Examples:
        # Create a benchmark
        benchmark(action="create", customer="acme-corp", use_case="sales intelligence")

        # Run a benchmark
        benchmark(action="run", customer="acme-corp", benchmark_id="benchmark-xxx")

        # Resume an incomplete run
        benchmark(action="run", customer="acme-corp", result_id="result-xxx")

        # Evaluate two results
        benchmark(action="evaluate", customer="acme-corp",
                  result_a_id="result-parallel-xxx", result_b_id="result-competitor-xxx")

        # Check status
        benchmark(action="status", customer="acme-corp", benchmark_id="benchmark-xxx")

        # List all for customer
        benchmark(action="list", customer="acme-corp")

        # Full pipeline
        benchmark(action="full", customer="acme-corp", use_case="competitor analysis")
    """
    # Validate action
    valid_actions = ["create", "run", "evaluate", "status", "list", "full"]
    if action not in valid_actions:
        return {
            "success": False,
            "error": f"Invalid action: {action}. Valid actions: {valid_actions}",
        }

    # Validate customer requirement
    if action in ["create", "run", "evaluate", "status", "full"] and not customer:
        return {
            "success": False,
            "error": f"Action '{action}' requires customer parameter",
        }

    # Dispatch to appropriate handler
    if action == "create":
        return create_benchmark_cli(
            customer=customer,
            use_case=use_case,
            processor=processor,
            min_questions=min_questions,
            max_questions=max_questions,
            verbose=verbose,
        )

    elif action == "run":
        return run_benchmark_cli(
            customer=customer,
            benchmark_id=benchmark_id,
            result_id=result_id,
            system=system,
            processor=processor,
            verbose=verbose,
        )

    elif action == "evaluate":
        if not result_a_id or not result_b_id:
            return {
                "success": False,
                "error": "Evaluate action requires both result_a_id and result_b_id",
            }
        return evaluate_benchmark_cli(
            customer=customer,
            result_a_id=result_a_id,
            result_b_id=result_b_id,
            save_report=True,
            verbose=verbose,
        )

    elif action == "status":
        if not any([benchmark_id, result_id, evaluation_id]):
            return {
                "success": False,
                "error": "Status action requires benchmark_id, result_id, or evaluation_id",
            }
        return benchmark_status_cli(
            customer=customer,
            benchmark_id=benchmark_id,
            result_id=result_id,
            evaluation_id=evaluation_id,
        )

    elif action == "list":
        return list_benchmarks_cli(
            customer=customer,
            include_results=True,
            include_evaluations=True,
        )

    elif action == "full":
        return full_benchmark_cli(
            customer=customer,
            use_case=use_case,
            processor=processor,
            comparison_system=comparison_system,
            min_questions=min_questions,
            max_questions=max_questions,
            verbose=verbose,
        )

    # Should never reach here
    return {"success": False, "error": f"Unhandled action: {action}"}


def _print_help():
    """Print help message."""
    help_text = """
Benchmark Tool - Create and evaluate Parallel.ai benchmarks

Usage:
    python -m tools benchmark '<json_args>'

Actions:
    create      Create a new benchmark from customer research
    run         Run a benchmark against Parallel.ai
    evaluate    Compare two benchmark results
    status      Check status of benchmark/result/evaluation
    list        List benchmarks, results, evaluations
    full        Run complete pipeline (create -> run -> evaluate)

Examples:
    # Create a benchmark
    python -m tools benchmark '{"action": "create", "customer": "acme-corp"}'

    # Create with use case hint
    python -m tools benchmark '{"action": "create", "customer": "acme-corp", "use_case": "sales intelligence"}'

    # Run a benchmark
    python -m tools benchmark '{"action": "run", "customer": "acme-corp", "benchmark_id": "benchmark-xxx"}'

    # Resume interrupted run
    python -m tools benchmark '{"action": "run", "customer": "acme-corp", "result_id": "result-xxx"}'

    # Run with verbose output
    python -m tools benchmark '{"action": "run", "customer": "acme-corp", "benchmark_id": "benchmark-xxx", "verbose": true}'

    # Evaluate two results
    python -m tools benchmark '{"action": "evaluate", "customer": "acme-corp", "result_a_id": "result-parallel-xxx", "result_b_id": "result-competitor-xxx"}'

    # Check benchmark status
    python -m tools benchmark '{"action": "status", "customer": "acme-corp", "benchmark_id": "benchmark-xxx"}'

    # Check result status
    python -m tools benchmark '{"action": "status", "customer": "acme-corp", "result_id": "result-xxx"}'

    # List all for a customer
    python -m tools benchmark '{"action": "list", "customer": "acme-corp"}'

    # List all customers
    python -m tools benchmark '{"action": "list"}'

    # Full pipeline
    python -m tools benchmark '{"action": "full", "customer": "acme-corp", "use_case": "competitor analysis", "verbose": true}'

Parameters:
    action          Required. One of: create, run, evaluate, status, list, full
    customer        Required for most actions. Customer/company name.
    benchmark_id    Benchmark ID (for run, status)
    result_id       Result ID (for resume, status)
    result_a_id     First result for evaluation (typically Parallel)
    result_b_id     Second result for evaluation (comparison system)
    evaluation_id   Evaluation ID (for status)
    use_case        Use case hint for question generation
    processor       API processor tier: lite, base, core, pro, ultra (default: base)
    system          System identifier for run (default: parallel)
    comparison_system  Comparison system for full pipeline
    min_questions   Minimum questions to generate (default: 30)
    max_questions   Maximum questions to generate (default: 70)
    verbose         Print detailed progress (default: false)

Output:
    JSON object with success status and action-specific results.
    Check 'success' field to determine if operation succeeded.
    On failure, 'error' field contains error message.
"""
    print(help_text)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ["-h", "--help", "help"]:
        _print_help()
        sys.exit(0)

    try:
        args = json.loads(sys.argv[1])
        result = benchmark(**args)
        print(json.dumps(result, indent=2))
    except json.JSONDecodeError as e:
        print(json.dumps({
            "success": False,
            "error": f"Invalid JSON argument: {e}",
            "usage": "python -m tools benchmark '<json_args>'",
        }, indent=2))
        sys.exit(1)
    except TypeError as e:
        print(json.dumps({
            "success": False,
            "error": f"Invalid parameter: {e}",
        }, indent=2))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": str(e),
        }, indent=2))
        sys.exit(1)
