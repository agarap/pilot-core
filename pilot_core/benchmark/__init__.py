"""
Benchmark system for evaluating Parallel.ai against competitor systems.

This module provides:
- Data models for benchmark questions, results, and evaluations
- Customer research and question generation
- Benchmark execution with resume capability
- Side-by-side comparison and scoring

Usage:
    from pilot_core.benchmark import (
        Benchmark, BenchmarkQuestion, BenchmarkResult, Evaluation,
        BenchmarkStatus, QuestionCategory, Difficulty
    )

    # Create a benchmark
    benchmark = Benchmark(
        customer="acme-corp",
        use_case="competitor analysis",
        questions=[...]
    )

    # Save/load benchmarks
    benchmark.save()
    loaded = Benchmark.load("acme-corp", "benchmark-001")
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml


# Base directory for benchmark storage
BENCHMARKS_DIR = Path("projects/benchmarks")


class QuestionCategory(str, Enum):
    """Category of benchmark question based on API capability."""
    SEARCH = "search"           # Web search capabilities
    ENRICHMENT = "enrichment"   # Data enrichment/extraction
    RESEARCH = "research"       # Deep research/analysis


class Difficulty(str, Enum):
    """Question difficulty level."""
    EASY = "easy"       # Simple, factual lookups
    MEDIUM = "medium"   # Multi-step or contextual
    HARD = "hard"       # Complex reasoning or synthesis


class BenchmarkStatus(str, Enum):
    """Status of a benchmark run."""
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class EvaluationWinner(str, Enum):
    """Winner of an evaluation comparison."""
    PARALLEL = "parallel"
    COMPARISON = "comparison"
    TIE = "tie"
    INCONCLUSIVE = "inconclusive"


@dataclass
class BenchmarkQuestion:
    """A single benchmark question."""
    id: str
    text: str
    category: QuestionCategory
    difficulty: Difficulty
    expected_answer_type: str  # e.g., "factual", "list", "analysis", "comparison"
    metadata: dict = field(default_factory=dict)

    # Optional fields for context
    context: Optional[str] = None  # Additional context for the question
    ground_truth: Optional[str] = None  # Known correct answer if available
    evaluation_criteria: list[str] = field(default_factory=list)  # How to evaluate

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "text": self.text,
            "category": self.category.value if isinstance(self.category, QuestionCategory) else self.category,
            "difficulty": self.difficulty.value if isinstance(self.difficulty, Difficulty) else self.difficulty,
            "expected_answer_type": self.expected_answer_type,
            "metadata": self.metadata,
            "context": self.context,
            "ground_truth": self.ground_truth,
            "evaluation_criteria": self.evaluation_criteria,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BenchmarkQuestion":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            text=data["text"],
            category=QuestionCategory(data["category"]) if data.get("category") else QuestionCategory.RESEARCH,
            difficulty=Difficulty(data["difficulty"]) if data.get("difficulty") else Difficulty.MEDIUM,
            expected_answer_type=data.get("expected_answer_type", "factual"),
            metadata=data.get("metadata", {}),
            context=data.get("context"),
            ground_truth=data.get("ground_truth"),
            evaluation_criteria=data.get("evaluation_criteria", []),
        )


@dataclass
class QuestionAnswer:
    """Answer to a single benchmark question."""
    question_id: str
    answer: str
    raw_response: dict = field(default_factory=dict)  # Full API response
    latency_ms: int = 0
    tokens_used: int = 0
    sources: list[str] = field(default_factory=list)  # URLs or references
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "question_id": self.question_id,
            "answer": self.answer,
            "raw_response": self.raw_response,
            "latency_ms": self.latency_ms,
            "tokens_used": self.tokens_used,
            "sources": self.sources,
            "error": self.error,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QuestionAnswer":
        """Create from dictionary."""
        return cls(
            question_id=data["question_id"],
            answer=data.get("answer", ""),
            raw_response=data.get("raw_response", {}),
            latency_ms=data.get("latency_ms", 0),
            tokens_used=data.get("tokens_used", 0),
            sources=data.get("sources", []),
            error=data.get("error"),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
        )


@dataclass
class Benchmark:
    """A complete benchmark for a customer."""
    id: str
    customer: str
    use_case: str
    questions: list[BenchmarkQuestion]
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: dict = field(default_factory=dict)

    # Research that informed question generation
    customer_research: dict = field(default_factory=dict)
    identified_use_cases: list[str] = field(default_factory=list)

    # Status tracking
    status: BenchmarkStatus = BenchmarkStatus.CREATED

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "customer": self.customer,
            "use_case": self.use_case,
            "questions": [q.to_dict() for q in self.questions],
            "created_at": self.created_at,
            "metadata": self.metadata,
            "customer_research": self.customer_research,
            "identified_use_cases": self.identified_use_cases,
            "status": self.status.value if isinstance(self.status, BenchmarkStatus) else self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Benchmark":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            customer=data["customer"],
            use_case=data.get("use_case", ""),
            questions=[BenchmarkQuestion.from_dict(q) for q in data.get("questions", [])],
            created_at=data.get("created_at", datetime.now().isoformat()),
            metadata=data.get("metadata", {}),
            customer_research=data.get("customer_research", {}),
            identified_use_cases=data.get("identified_use_cases", []),
            status=BenchmarkStatus(data.get("status", "created")),
        )

    def save(self, base_dir: Optional[Path] = None) -> Path:
        """Save benchmark to YAML file."""
        base = base_dir or BENCHMARKS_DIR
        customer_dir = base / self.customer
        customer_dir.mkdir(parents=True, exist_ok=True)

        path = customer_dir / f"{self.id}.yaml"
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        return path

    @classmethod
    def load(cls, customer: str, benchmark_id: str, base_dir: Optional[Path] = None) -> "Benchmark":
        """Load benchmark from YAML file."""
        base = base_dir or BENCHMARKS_DIR
        path = base / customer / f"{benchmark_id}.yaml"

        with open(path) as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data)

    @classmethod
    def generate_id(cls) -> str:
        """Generate a unique benchmark ID."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_id = uuid.uuid4().hex[:6]
        return f"benchmark-{timestamp}-{short_id}"

    def question_counts(self) -> dict[str, int]:
        """Get counts by category and difficulty."""
        by_category = {}
        by_difficulty = {}

        for q in self.questions:
            cat = q.category.value if isinstance(q.category, QuestionCategory) else q.category
            diff = q.difficulty.value if isinstance(q.difficulty, Difficulty) else q.difficulty

            by_category[cat] = by_category.get(cat, 0) + 1
            by_difficulty[diff] = by_difficulty.get(diff, 0) + 1

        return {
            "total": len(self.questions),
            "by_category": by_category,
            "by_difficulty": by_difficulty,
        }


@dataclass
class BenchmarkResult:
    """Results from running a benchmark against a system."""
    id: str
    benchmark_id: str
    system: str  # "parallel" or comparison system name
    answers: list[QuestionAnswer]

    # Timing and metadata
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    status: BenchmarkStatus = BenchmarkStatus.IN_PROGRESS

    # Aggregate metrics
    total_latency_ms: int = 0
    total_tokens: int = 0
    success_count: int = 0
    error_count: int = 0

    # Configuration used
    processor: str = "base"
    config: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "benchmark_id": self.benchmark_id,
            "system": self.system,
            "answers": [a.to_dict() for a in self.answers],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status.value if isinstance(self.status, BenchmarkStatus) else self.status,
            "total_latency_ms": self.total_latency_ms,
            "total_tokens": self.total_tokens,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "processor": self.processor,
            "config": self.config,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BenchmarkResult":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            benchmark_id=data["benchmark_id"],
            system=data["system"],
            answers=[QuestionAnswer.from_dict(a) for a in data.get("answers", [])],
            started_at=data.get("started_at", datetime.now().isoformat()),
            completed_at=data.get("completed_at"),
            status=BenchmarkStatus(data.get("status", "in_progress")),
            total_latency_ms=data.get("total_latency_ms", 0),
            total_tokens=data.get("total_tokens", 0),
            success_count=data.get("success_count", 0),
            error_count=data.get("error_count", 0),
            processor=data.get("processor", "base"),
            config=data.get("config", {}),
        )

    def save(self, customer: str, base_dir: Optional[Path] = None) -> Path:
        """Save result to YAML file."""
        base = base_dir or BENCHMARKS_DIR
        results_dir = base / customer / "results"
        results_dir.mkdir(parents=True, exist_ok=True)

        path = results_dir / f"{self.id}.yaml"
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        return path

    @classmethod
    def load(cls, customer: str, result_id: str, base_dir: Optional[Path] = None) -> "BenchmarkResult":
        """Load result from YAML file."""
        base = base_dir or BENCHMARKS_DIR
        path = base / customer / "results" / f"{result_id}.yaml"

        with open(path) as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data)

    @classmethod
    def generate_id(cls, system: str) -> str:
        """Generate a unique result ID."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_id = uuid.uuid4().hex[:6]
        return f"result-{system}-{timestamp}-{short_id}"

    def complete(self) -> None:
        """Mark result as complete and calculate aggregates."""
        self.completed_at = datetime.now().isoformat()
        self.status = BenchmarkStatus.COMPLETED

        # Calculate aggregates
        self.total_latency_ms = sum(a.latency_ms for a in self.answers)
        self.total_tokens = sum(a.tokens_used for a in self.answers)
        self.success_count = sum(1 for a in self.answers if not a.error)
        self.error_count = sum(1 for a in self.answers if a.error)

    def answered_question_ids(self) -> set[str]:
        """Get IDs of questions that have been answered."""
        return {a.question_id for a in self.answers}


@dataclass
class QuestionScore:
    """Score for a single question comparison."""
    question_id: str

    # Individual scores (0-10 scale)
    parallel_score: float
    comparison_score: float

    # Detailed scoring breakdown
    accuracy_parallel: float = 0.0
    accuracy_comparison: float = 0.0
    completeness_parallel: float = 0.0
    completeness_comparison: float = 0.0
    relevance_parallel: float = 0.0
    relevance_comparison: float = 0.0

    # Winner for this question
    winner: EvaluationWinner = EvaluationWinner.TIE
    confidence: float = 0.0  # 0-1 confidence in winner determination

    # Reasoning
    reasoning: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "question_id": self.question_id,
            "parallel_score": self.parallel_score,
            "comparison_score": self.comparison_score,
            "accuracy_parallel": self.accuracy_parallel,
            "accuracy_comparison": self.accuracy_comparison,
            "completeness_parallel": self.completeness_parallel,
            "completeness_comparison": self.completeness_comparison,
            "relevance_parallel": self.relevance_parallel,
            "relevance_comparison": self.relevance_comparison,
            "winner": self.winner.value if isinstance(self.winner, EvaluationWinner) else self.winner,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QuestionScore":
        """Create from dictionary."""
        return cls(
            question_id=data["question_id"],
            parallel_score=data.get("parallel_score", 0),
            comparison_score=data.get("comparison_score", 0),
            accuracy_parallel=data.get("accuracy_parallel", 0),
            accuracy_comparison=data.get("accuracy_comparison", 0),
            completeness_parallel=data.get("completeness_parallel", 0),
            completeness_comparison=data.get("completeness_comparison", 0),
            relevance_parallel=data.get("relevance_parallel", 0),
            relevance_comparison=data.get("relevance_comparison", 0),
            winner=EvaluationWinner(data.get("winner", "tie")),
            confidence=data.get("confidence", 0),
            reasoning=data.get("reasoning", ""),
        )


@dataclass
class AggregateScores:
    """Aggregate scores across all questions."""
    # Overall scores
    parallel_average: float = 0.0
    comparison_average: float = 0.0

    # By category
    by_category: dict = field(default_factory=dict)  # category -> {parallel: x, comparison: y}

    # By difficulty
    by_difficulty: dict = field(default_factory=dict)  # difficulty -> {parallel: x, comparison: y}

    # Win counts
    parallel_wins: int = 0
    comparison_wins: int = 0
    ties: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "parallel_average": self.parallel_average,
            "comparison_average": self.comparison_average,
            "by_category": self.by_category,
            "by_difficulty": self.by_difficulty,
            "parallel_wins": self.parallel_wins,
            "comparison_wins": self.comparison_wins,
            "ties": self.ties,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AggregateScores":
        """Create from dictionary."""
        return cls(
            parallel_average=data.get("parallel_average", 0),
            comparison_average=data.get("comparison_average", 0),
            by_category=data.get("by_category", {}),
            by_difficulty=data.get("by_difficulty", {}),
            parallel_wins=data.get("parallel_wins", 0),
            comparison_wins=data.get("comparison_wins", 0),
            ties=data.get("ties", 0),
        )


@dataclass
class Evaluation:
    """Complete evaluation comparing two benchmark results."""
    id: str
    benchmark_id: str
    parallel_result_id: str
    comparison_result_id: str
    comparison_system: str

    # Scores
    question_scores: list[QuestionScore]
    aggregate_scores: AggregateScores

    # Overall winner
    winner: EvaluationWinner
    confidence: float  # 0-1 confidence in overall winner

    # Timing
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Summary
    summary: str = ""
    strengths_parallel: list[str] = field(default_factory=list)
    strengths_comparison: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "benchmark_id": self.benchmark_id,
            "parallel_result_id": self.parallel_result_id,
            "comparison_result_id": self.comparison_result_id,
            "comparison_system": self.comparison_system,
            "question_scores": [s.to_dict() for s in self.question_scores],
            "aggregate_scores": self.aggregate_scores.to_dict(),
            "winner": self.winner.value if isinstance(self.winner, EvaluationWinner) else self.winner,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "summary": self.summary,
            "strengths_parallel": self.strengths_parallel,
            "strengths_comparison": self.strengths_comparison,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Evaluation":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            benchmark_id=data["benchmark_id"],
            parallel_result_id=data["parallel_result_id"],
            comparison_result_id=data["comparison_result_id"],
            comparison_system=data.get("comparison_system", "unknown"),
            question_scores=[QuestionScore.from_dict(s) for s in data.get("question_scores", [])],
            aggregate_scores=AggregateScores.from_dict(data.get("aggregate_scores", {})),
            winner=EvaluationWinner(data.get("winner", "inconclusive")),
            confidence=data.get("confidence", 0),
            created_at=data.get("created_at", datetime.now().isoformat()),
            summary=data.get("summary", ""),
            strengths_parallel=data.get("strengths_parallel", []),
            strengths_comparison=data.get("strengths_comparison", []),
        )

    def save(self, customer: str, base_dir: Optional[Path] = None) -> Path:
        """Save evaluation to YAML file."""
        base = base_dir or BENCHMARKS_DIR
        evals_dir = base / customer / "evaluations"
        evals_dir.mkdir(parents=True, exist_ok=True)

        path = evals_dir / f"{self.id}.yaml"
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        return path

    @classmethod
    def load(cls, customer: str, eval_id: str, base_dir: Optional[Path] = None) -> "Evaluation":
        """Load evaluation from YAML file."""
        base = base_dir or BENCHMARKS_DIR
        path = base / customer / "evaluations" / f"{eval_id}.yaml"

        with open(path) as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data)

    @classmethod
    def generate_id(cls) -> str:
        """Generate a unique evaluation ID."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_id = uuid.uuid4().hex[:6]
        return f"eval-{timestamp}-{short_id}"


# Utility functions

def list_benchmarks(customer: str, base_dir: Optional[Path] = None) -> list[str]:
    """List all benchmark IDs for a customer."""
    base = base_dir or BENCHMARKS_DIR
    customer_dir = base / customer

    if not customer_dir.exists():
        return []

    benchmarks = []
    for path in customer_dir.glob("benchmark-*.yaml"):
        benchmarks.append(path.stem)

    return sorted(benchmarks, reverse=True)


def list_results(customer: str, base_dir: Optional[Path] = None) -> list[str]:
    """List all result IDs for a customer."""
    base = base_dir or BENCHMARKS_DIR
    results_dir = base / customer / "results"

    if not results_dir.exists():
        return []

    results = []
    for path in results_dir.glob("result-*.yaml"):
        results.append(path.stem)

    return sorted(results, reverse=True)


def list_evaluations(customer: str, base_dir: Optional[Path] = None) -> list[str]:
    """List all evaluation IDs for a customer."""
    base = base_dir or BENCHMARKS_DIR
    evals_dir = base / customer / "evaluations"

    if not evals_dir.exists():
        return []

    evals = []
    for path in evals_dir.glob("eval-*.yaml"):
        evals.append(path.stem)

    return sorted(evals, reverse=True)


def list_customers(base_dir: Optional[Path] = None) -> list[str]:
    """List all customers with benchmarks."""
    base = base_dir or BENCHMARKS_DIR

    if not base.exists():
        return []

    customers = []
    for path in base.iterdir():
        if path.is_dir() and not path.name.startswith("."):
            customers.append(path.name)

    return sorted(customers)
