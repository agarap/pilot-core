"""
Side-by-side benchmark evaluation.

This module handles comparing benchmark results between Parallel.ai and
competitor systems, scoring answers, and determining winners.

Usage:
    from lib.benchmark.evaluator import (
        score_answer,
        compare_answers,
        evaluate_benchmark,
        generate_report,
    )

    # Full evaluation
    evaluation = evaluate_benchmark(parallel_result, comparison_result, benchmark)
    report = generate_report(evaluation, benchmark)
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import (
    Benchmark,
    BenchmarkQuestion,
    BenchmarkResult,
    QuestionAnswer,
    Evaluation,
    QuestionScore,
    AggregateScores,
    EvaluationWinner,
    QuestionCategory,
    Difficulty,
    BENCHMARKS_DIR,
)

# Import Parallel API for LLM-based evaluation
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tools.parallel_task import parallel_task_quick


def score_answer(
    question: BenchmarkQuestion,
    answer: QuestionAnswer,
    criteria: Optional[list[str]] = None,
) -> dict:
    """
    Score a single answer against quality criteria.

    Uses LLM to evaluate answer quality on multiple dimensions:
    - Accuracy: Correctness of information
    - Completeness: Coverage of the question
    - Relevance: Focus on what was asked
    - Clarity: How well-organized and clear

    Args:
        question: The benchmark question
        answer: The answer to score
        criteria: Optional specific criteria (uses question.evaluation_criteria if not provided)

    Returns:
        dict with scores (0-10) for each dimension and overall score
    """
    if answer.error:
        return {
            "accuracy": 0,
            "completeness": 0,
            "relevance": 0,
            "clarity": 0,
            "overall": 0,
            "error": answer.error,
        }

    eval_criteria = criteria or question.evaluation_criteria or []

    # Build evaluation prompt
    prompt = f"""Evaluate this answer to a benchmark question.

Question: {question.text}
Expected Answer Type: {question.expected_answer_type}
{f'Ground Truth: {question.ground_truth}' if question.ground_truth else ''}
{f'Evaluation Criteria: {", ".join(eval_criteria)}' if eval_criteria else ''}

Answer to evaluate:
{answer.answer[:3000]}  # Truncate very long answers

Score the answer on these dimensions (0-10 scale):
1. Accuracy: Is the information correct and factually accurate?
2. Completeness: Does it fully address the question?
3. Relevance: Does it focus on what was asked?
4. Clarity: Is it well-organized and easy to understand?

Return a JSON object with scores for: accuracy, completeness, relevance, clarity, overall (average), reasoning (brief explanation)"""

    result = parallel_task_quick(prompt, processor="lite")

    if "error" in result:
        # Return neutral scores on error
        return {
            "accuracy": 5,
            "completeness": 5,
            "relevance": 5,
            "clarity": 5,
            "overall": 5,
            "reasoning": f"Evaluation error: {result['error']}",
        }

    return _parse_scores(result.get("output", {}))


def _parse_scores(output: any) -> dict:
    """Parse scores from LLM output."""
    default = {
        "accuracy": 5,
        "completeness": 5,
        "relevance": 5,
        "clarity": 5,
        "overall": 5,
        "reasoning": "",
    }

    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            return default

    if not isinstance(output, dict):
        return default

    # Extract scores, ensuring they're in valid range
    def get_score(key: str) -> float:
        val = output.get(key, 5)
        try:
            score = float(val)
            return max(0, min(10, score))
        except (ValueError, TypeError):
            return 5

    scores = {
        "accuracy": get_score("accuracy"),
        "completeness": get_score("completeness"),
        "relevance": get_score("relevance"),
        "clarity": get_score("clarity"),
        "reasoning": str(output.get("reasoning", "")),
    }

    # Calculate overall if not provided
    if "overall" in output:
        scores["overall"] = get_score("overall")
    else:
        scores["overall"] = sum([
            scores["accuracy"],
            scores["completeness"],
            scores["relevance"],
            scores["clarity"],
        ]) / 4

    return scores


def compare_answers(
    question: BenchmarkQuestion,
    answer_a: QuestionAnswer,
    answer_b: QuestionAnswer,
    system_a: str = "System A",
    system_b: str = "System B",
) -> dict:
    """
    Compare two answers head-to-head.

    Args:
        question: The benchmark question
        answer_a: First answer (typically Parallel)
        answer_b: Second answer (comparison system)
        system_a: Name for first system
        system_b: Name for second system

    Returns:
        dict with scores for both, winner, and reasoning
    """
    # Handle error cases
    if answer_a.error and answer_b.error:
        return {
            "score_a": 0,
            "score_b": 0,
            "winner": "tie",
            "confidence": 0.5,
            "reasoning": "Both answers had errors",
        }
    elif answer_a.error:
        return {
            "score_a": 0,
            "score_b": 7,
            "winner": "b",
            "confidence": 0.9,
            "reasoning": f"{system_a} error: {answer_a.error}",
        }
    elif answer_b.error:
        return {
            "score_a": 7,
            "score_b": 0,
            "winner": "a",
            "confidence": 0.9,
            "reasoning": f"{system_b} error: {answer_b.error}",
        }

    # Build comparison prompt
    prompt = f"""Compare these two answers to the same question. Determine which is better.

Question: {question.text}
Expected Answer Type: {question.expected_answer_type}
{f'Ground Truth: {question.ground_truth}' if question.ground_truth else ''}

{system_a}'s Answer:
{answer_a.answer[:2000]}

{system_b}'s Answer:
{answer_b.answer[:2000]}

Evaluate both answers on:
1. Accuracy of information
2. Completeness of coverage
3. Relevance to the question
4. Quality of sources/evidence

Return a JSON object with:
- score_a: Overall score for {system_a} (0-10)
- score_b: Overall score for {system_b} (0-10)
- winner: "a" if {system_a} is better, "b" if {system_b} is better, "tie" if equal
- confidence: How confident you are in this judgment (0-1)
- reasoning: Brief explanation of the comparison"""

    result = parallel_task_quick(prompt, processor="lite")

    if "error" in result:
        return {
            "score_a": 5,
            "score_b": 5,
            "winner": "tie",
            "confidence": 0.3,
            "reasoning": f"Comparison error: {result['error']}",
        }

    return _parse_comparison(result.get("output", {}))


def _parse_comparison(output: any) -> dict:
    """Parse comparison result from LLM output."""
    default = {
        "score_a": 5,
        "score_b": 5,
        "winner": "tie",
        "confidence": 0.5,
        "reasoning": "",
    }

    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            return default

    if not isinstance(output, dict):
        return default

    def get_score(key: str) -> float:
        val = output.get(key, 5)
        try:
            return max(0, min(10, float(val)))
        except (ValueError, TypeError):
            return 5

    def get_confidence() -> float:
        val = output.get("confidence", 0.5)
        try:
            return max(0, min(1, float(val)))
        except (ValueError, TypeError):
            return 0.5

    winner = output.get("winner", "tie")
    if winner not in ["a", "b", "tie"]:
        winner = "tie"

    return {
        "score_a": get_score("score_a"),
        "score_b": get_score("score_b"),
        "winner": winner,
        "confidence": get_confidence(),
        "reasoning": str(output.get("reasoning", "")),
    }


def evaluate_benchmark(
    parallel_result: BenchmarkResult,
    comparison_result: BenchmarkResult,
    benchmark: Benchmark,
) -> Evaluation:
    """
    Full evaluation comparing two benchmark results.

    Compares answers question-by-question and aggregates results.

    Args:
        parallel_result: Results from Parallel.ai
        comparison_result: Results from comparison system
        benchmark: The benchmark that was run

    Returns:
        Evaluation with detailed scores and winner
    """
    # Build answer lookup
    parallel_answers = {a.question_id: a for a in parallel_result.answers}
    comparison_answers = {a.question_id: a for a in comparison_result.answers}

    question_scores = []
    category_scores = {}  # category -> {parallel: [], comparison: []}
    difficulty_scores = {}  # difficulty -> {parallel: [], comparison: []}

    for question in benchmark.questions:
        parallel_answer = parallel_answers.get(question.id)
        comparison_answer = comparison_answers.get(question.id)

        if not parallel_answer or not comparison_answer:
            continue

        # Compare this question
        comparison = compare_answers(
            question=question,
            answer_a=parallel_answer,
            answer_b=comparison_answer,
            system_a="Parallel",
            system_b=comparison_result.system,
        )

        # Determine winner
        if comparison["winner"] == "a":
            winner = EvaluationWinner.PARALLEL
        elif comparison["winner"] == "b":
            winner = EvaluationWinner.COMPARISON
        else:
            winner = EvaluationWinner.TIE

        # Create question score
        q_score = QuestionScore(
            question_id=question.id,
            parallel_score=comparison["score_a"],
            comparison_score=comparison["score_b"],
            winner=winner,
            confidence=comparison["confidence"],
            reasoning=comparison["reasoning"],
        )
        question_scores.append(q_score)

        # Track by category
        cat = question.category.value if isinstance(question.category, QuestionCategory) else question.category
        if cat not in category_scores:
            category_scores[cat] = {"parallel": [], "comparison": []}
        category_scores[cat]["parallel"].append(comparison["score_a"])
        category_scores[cat]["comparison"].append(comparison["score_b"])

        # Track by difficulty
        diff = question.difficulty.value if isinstance(question.difficulty, Difficulty) else question.difficulty
        if diff not in difficulty_scores:
            difficulty_scores[diff] = {"parallel": [], "comparison": []}
        difficulty_scores[diff]["parallel"].append(comparison["score_a"])
        difficulty_scores[diff]["comparison"].append(comparison["score_b"])

    # Calculate aggregates
    parallel_total = sum(s.parallel_score for s in question_scores)
    comparison_total = sum(s.comparison_score for s in question_scores)
    count = len(question_scores) or 1

    parallel_wins = sum(1 for s in question_scores if s.winner == EvaluationWinner.PARALLEL)
    comparison_wins = sum(1 for s in question_scores if s.winner == EvaluationWinner.COMPARISON)
    ties = sum(1 for s in question_scores if s.winner == EvaluationWinner.TIE)

    # Category averages
    by_category = {}
    for cat, scores in category_scores.items():
        p_avg = sum(scores["parallel"]) / len(scores["parallel"]) if scores["parallel"] else 0
        c_avg = sum(scores["comparison"]) / len(scores["comparison"]) if scores["comparison"] else 0
        by_category[cat] = {"parallel": round(p_avg, 2), "comparison": round(c_avg, 2)}

    # Difficulty averages
    by_difficulty = {}
    for diff, scores in difficulty_scores.items():
        p_avg = sum(scores["parallel"]) / len(scores["parallel"]) if scores["parallel"] else 0
        c_avg = sum(scores["comparison"]) / len(scores["comparison"]) if scores["comparison"] else 0
        by_difficulty[diff] = {"parallel": round(p_avg, 2), "comparison": round(c_avg, 2)}

    aggregate = AggregateScores(
        parallel_average=round(parallel_total / count, 2),
        comparison_average=round(comparison_total / count, 2),
        by_category=by_category,
        by_difficulty=by_difficulty,
        parallel_wins=parallel_wins,
        comparison_wins=comparison_wins,
        ties=ties,
    )

    # Determine overall winner
    if parallel_wins > comparison_wins + ties:
        winner = EvaluationWinner.PARALLEL
        confidence = parallel_wins / count
    elif comparison_wins > parallel_wins + ties:
        winner = EvaluationWinner.COMPARISON
        confidence = comparison_wins / count
    elif abs(aggregate.parallel_average - aggregate.comparison_average) > 1:
        if aggregate.parallel_average > aggregate.comparison_average:
            winner = EvaluationWinner.PARALLEL
        else:
            winner = EvaluationWinner.COMPARISON
        confidence = 0.6
    else:
        winner = EvaluationWinner.TIE
        confidence = 0.5

    # Identify strengths
    strengths_parallel = _identify_strengths(question_scores, benchmark.questions, EvaluationWinner.PARALLEL)
    strengths_comparison = _identify_strengths(question_scores, benchmark.questions, EvaluationWinner.COMPARISON)

    # Create evaluation
    evaluation = Evaluation(
        id=Evaluation.generate_id(),
        benchmark_id=benchmark.id,
        parallel_result_id=parallel_result.id,
        comparison_result_id=comparison_result.id,
        comparison_system=comparison_result.system,
        question_scores=question_scores,
        aggregate_scores=aggregate,
        winner=winner,
        confidence=confidence,
        strengths_parallel=strengths_parallel,
        strengths_comparison=strengths_comparison,
    )

    return evaluation


def _identify_strengths(
    scores: list[QuestionScore],
    questions: list[BenchmarkQuestion],
    system: EvaluationWinner,
) -> list[str]:
    """Identify strengths for a system based on where it won."""
    strengths = []
    question_map = {q.id: q for q in questions}

    # Group wins by category
    category_wins = {}
    difficulty_wins = {}

    for score in scores:
        if score.winner != system:
            continue

        question = question_map.get(score.question_id)
        if not question:
            continue

        cat = question.category.value if isinstance(question.category, QuestionCategory) else question.category
        diff = question.difficulty.value if isinstance(question.difficulty, Difficulty) else question.difficulty

        category_wins[cat] = category_wins.get(cat, 0) + 1
        difficulty_wins[diff] = difficulty_wins.get(diff, 0) + 1

    # Identify patterns
    for cat, count in category_wins.items():
        if count >= 3:
            strengths.append(f"Strong in {cat} questions ({count} wins)")

    for diff, count in difficulty_wins.items():
        if count >= 3:
            strengths.append(f"Excels at {diff} difficulty ({count} wins)")

    return strengths[:5]  # Top 5 strengths


def generate_report(evaluation: Evaluation, benchmark: Benchmark) -> str:
    """
    Generate a markdown report for an evaluation.

    Args:
        evaluation: The evaluation to report on
        benchmark: The benchmark that was evaluated

    Returns:
        Markdown string with full report
    """
    agg = evaluation.aggregate_scores

    # Header
    report = f"""# Benchmark Evaluation Report

**Customer:** {benchmark.customer}
**Use Case:** {benchmark.use_case}
**Generated:** {evaluation.created_at}

## Summary

| Metric | Parallel | {evaluation.comparison_system} |
|--------|----------|------------------------------|
| Average Score | {agg.parallel_average:.1f} | {agg.comparison_average:.1f} |
| Questions Won | {agg.parallel_wins} | {agg.comparison_wins} |
| Ties | {agg.ties} | - |

**Winner: {evaluation.winner.value.upper()}** (Confidence: {evaluation.confidence:.0%})

## Scores by Category

| Category | Parallel | {evaluation.comparison_system} |
|----------|----------|------------------------------|
"""

    for cat, scores in agg.by_category.items():
        report += f"| {cat.title()} | {scores['parallel']:.1f} | {scores['comparison']:.1f} |\n"

    report += f"""
## Scores by Difficulty

| Difficulty | Parallel | {evaluation.comparison_system} |
|------------|----------|------------------------------|
"""

    for diff, scores in agg.by_difficulty.items():
        report += f"| {diff.title()} | {scores['parallel']:.1f} | {scores['comparison']:.1f} |\n"

    # Strengths
    if evaluation.strengths_parallel:
        report += "\n## Parallel Strengths\n\n"
        for s in evaluation.strengths_parallel:
            report += f"- {s}\n"

    if evaluation.strengths_comparison:
        report += f"\n## {evaluation.comparison_system} Strengths\n\n"
        for s in evaluation.strengths_comparison:
            report += f"- {s}\n"

    # Question details (top wins/losses)
    report += "\n## Notable Results\n\n"

    # Best Parallel wins
    parallel_wins = sorted(
        [s for s in evaluation.question_scores if s.winner == EvaluationWinner.PARALLEL],
        key=lambda s: s.parallel_score - s.comparison_score,
        reverse=True,
    )[:3]

    if parallel_wins:
        report += "### Best Parallel Wins\n\n"
        for score in parallel_wins:
            report += f"- **{score.question_id}**: {score.parallel_score:.1f} vs {score.comparison_score:.1f}\n"
            if score.reasoning:
                report += f"  - {score.reasoning[:200]}\n"

    # Best comparison wins
    comparison_wins = sorted(
        [s for s in evaluation.question_scores if s.winner == EvaluationWinner.COMPARISON],
        key=lambda s: s.comparison_score - s.parallel_score,
        reverse=True,
    )[:3]

    if comparison_wins:
        report += f"\n### Best {evaluation.comparison_system} Wins\n\n"
        for score in comparison_wins:
            report += f"- **{score.question_id}**: {score.comparison_score:.1f} vs {score.parallel_score:.1f}\n"
            if score.reasoning:
                report += f"  - {score.reasoning[:200]}\n"

    # Footer
    report += f"""
---

**Evaluation ID:** {evaluation.id}
**Benchmark ID:** {benchmark.id}
**Questions Evaluated:** {len(evaluation.question_scores)}
"""

    return report


def quick_evaluate(
    customer: str,
    parallel_result_id: str,
    comparison_result_id: str,
    save: bool = True,
) -> Evaluation:
    """
    Quick evaluation helper that loads results and benchmark.

    Args:
        customer: Customer name
        parallel_result_id: ID of Parallel result
        comparison_result_id: ID of comparison result
        save: Whether to save evaluation

    Returns:
        Evaluation object
    """
    parallel_result = BenchmarkResult.load(customer, parallel_result_id)
    comparison_result = BenchmarkResult.load(customer, comparison_result_id)
    benchmark = Benchmark.load(customer, parallel_result.benchmark_id)

    evaluation = evaluate_benchmark(parallel_result, comparison_result, benchmark)

    if save:
        evaluation.save(customer)

    return evaluation


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 4:
        print("Usage: python -m lib.benchmark.evaluator <customer> <parallel_result_id> <comparison_result_id>")
        sys.exit(1)

    customer = sys.argv[1]
    parallel_id = sys.argv[2]
    comparison_id = sys.argv[3]

    print(f"Evaluating {parallel_id} vs {comparison_id}...")

    evaluation = quick_evaluate(customer, parallel_id, comparison_id)

    # Load benchmark for report
    parallel_result = BenchmarkResult.load(customer, parallel_id)
    benchmark = Benchmark.load(customer, parallel_result.benchmark_id)

    report = generate_report(evaluation, benchmark)
    print(report)

    print(f"\nEvaluation saved: {evaluation.id}")
