"""
Benchmark question creation and customer research.

This module handles:
- Deep customer research using Parallel.ai
- Use case identification from research
- Question generation based on customer context
- Benchmark validation

Usage:
    from lib.benchmark.creator import (
        research_customer,
        extract_use_cases,
        generate_questions,
        create_benchmark,
    )

    # Full workflow
    benchmark = create_benchmark("acme-corp", use_case_hint="sales intelligence")

    # Step by step
    research = research_customer("acme-corp")
    use_cases = extract_use_cases(research)
    questions = generate_questions("acme-corp", use_cases)
"""

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from . import (
    Benchmark,
    BenchmarkQuestion,
    BenchmarkStatus,
    QuestionCategory,
    Difficulty,
    BENCHMARKS_DIR,
)

# Import Parallel API tools
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tools.parallel_task import parallel_task_quick, parallel_task_create, parallel_task_result
from tools.web_search import web_search


def research_customer(
    customer_name: str,
    use_case_hint: Optional[str] = None,
    processor: str = "core",
) -> dict:
    """
    Research a customer deeply to understand their business and use cases.

    Uses Parallel.ai Task API to gather comprehensive information about:
    - Company overview and industry
    - Products and services
    - Target market and customers
    - Key business challenges
    - Potential use cases for web search/enrichment

    Args:
        customer_name: Company name to research
        use_case_hint: Optional hint about intended use case
        processor: Parallel processor tier (default: core for thorough research)

    Returns:
        dict with research findings including:
        - company_overview: General company info
        - industry: Industry classification
        - products_services: List of offerings
        - target_market: Customer segments
        - challenges: Business challenges
        - potential_use_cases: Identified use cases
        - raw_output: Full API response
    """
    # Build research query
    query_parts = [
        f"Research {customer_name} comprehensively.",
        "Provide:",
        "1. Company overview (founding, headquarters, size, funding)",
        "2. Industry and market position",
        "3. Main products and services",
        "4. Target customers and market segments",
        "5. Key business challenges and pain points",
        "6. How they might benefit from web search, data enrichment, or research automation",
    ]

    if use_case_hint:
        query_parts.append(f"7. Specifically focus on their needs for: {use_case_hint}")

    query = "\n".join(query_parts)

    # Execute research
    result = parallel_task_quick(query, processor=processor)

    if "error" in result:
        return {
            "error": result["error"],
            "customer": customer_name,
            "use_case_hint": use_case_hint,
        }

    # Parse output
    output = result.get("output", {})
    if isinstance(output, str):
        # Try to parse if it's a JSON string
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            output = {"raw_text": output}

    return {
        "customer": customer_name,
        "use_case_hint": use_case_hint,
        "company_overview": _extract_section(output, ["company_overview", "overview", "about"]),
        "industry": _extract_section(output, ["industry", "sector", "market"]),
        "products_services": _extract_section(output, ["products", "services", "offerings", "products_services"]),
        "target_market": _extract_section(output, ["target_market", "customers", "segments", "target_customers"]),
        "challenges": _extract_section(output, ["challenges", "pain_points", "problems"]),
        "potential_use_cases": _extract_section(output, ["use_cases", "potential_use_cases", "applications"]),
        "raw_output": output,
        "researched_at": datetime.now().isoformat(),
    }


def _extract_section(output: dict, keys: list[str]) -> any:
    """Extract a section from output trying multiple key variations."""
    if not isinstance(output, dict):
        return None

    for key in keys:
        if key in output:
            return output[key]

        # Try nested access
        for top_key in output:
            if isinstance(output[top_key], dict) and key in output[top_key]:
                return output[top_key][key]

    return None


def extract_use_cases(research: dict, max_use_cases: int = 5) -> list[dict]:
    """
    Identify plausible use cases from customer research.

    Analyzes research findings to identify specific use cases that would
    benefit from Parallel.ai capabilities (search, enrichment, research).

    Args:
        research: Research dict from research_customer()
        max_use_cases: Maximum number of use cases to return

    Returns:
        List of use case dicts with:
        - name: Short use case name
        - description: Detailed description
        - category: Primary category (search|enrichment|research)
        - value_proposition: How this helps the customer
        - question_themes: Themes for question generation
    """
    if "error" in research:
        return []

    # Extract relevant context
    industry = research.get("industry", "unknown")
    products = research.get("products_services", [])
    challenges = research.get("challenges", [])
    potential = research.get("potential_use_cases", [])
    hint = research.get("use_case_hint", "")

    # Build use case synthesis query
    query = f"""Based on this customer research, identify {max_use_cases} specific use cases
where Parallel.ai's capabilities would provide value.

Customer: {research.get('customer', 'Unknown')}
Industry: {industry}
Products/Services: {json.dumps(products) if isinstance(products, list) else products}
Challenges: {json.dumps(challenges) if isinstance(challenges, list) else challenges}
Suggested Use Cases: {json.dumps(potential) if isinstance(potential, list) else potential}
{f'Focus Area: {hint}' if hint else ''}

For each use case, provide:
1. name: Short identifier
2. description: What the use case involves
3. category: One of "search" (web search), "enrichment" (data extraction), or "research" (deep analysis)
4. value_proposition: Specific business value
5. question_themes: 3-5 themes for benchmark questions

Return as a JSON array of use case objects."""

    result = parallel_task_quick(query, processor="base")

    if "error" in result:
        # Return default use cases if research fails
        return _default_use_cases(research.get("customer", "unknown"))

    output = result.get("output", {})

    # Try to extract use cases from output
    use_cases = _parse_use_cases(output)

    if not use_cases:
        use_cases = _default_use_cases(research.get("customer", "unknown"))

    return use_cases[:max_use_cases]


def _parse_use_cases(output: any) -> list[dict]:
    """Parse use cases from API output."""
    if isinstance(output, list):
        return output

    if isinstance(output, dict):
        # Look for use_cases key
        for key in ["use_cases", "cases", "results", "items"]:
            if key in output and isinstance(output[key], list):
                return output[key]

        # Maybe the dict itself represents a single use case
        if "name" in output and "description" in output:
            return [output]

    if isinstance(output, str):
        # Try to parse as JSON
        try:
            parsed = json.loads(output)
            return _parse_use_cases(parsed)
        except json.JSONDecodeError:
            pass

    return []


def _default_use_cases(customer: str) -> list[dict]:
    """Return default use cases when extraction fails."""
    return [
        {
            "name": "competitor_intelligence",
            "description": f"Track and analyze {customer}'s competitors",
            "category": "research",
            "value_proposition": "Stay ahead of competitive moves",
            "question_themes": ["competitor news", "market share", "product launches", "pricing"],
        },
        {
            "name": "lead_enrichment",
            "description": "Enrich prospect and customer data",
            "category": "enrichment",
            "value_proposition": "Better targeting and personalization",
            "question_themes": ["company info", "contact details", "firmographics", "technographics"],
        },
        {
            "name": "market_research",
            "description": "Research market trends and opportunities",
            "category": "research",
            "value_proposition": "Identify growth opportunities",
            "question_themes": ["industry trends", "market size", "emerging technologies", "regulations"],
        },
    ]


def generate_questions(
    customer: str,
    use_cases: list[dict],
    count_range: tuple[int, int] = (30, 70),
    processor: str = "base",
) -> list[BenchmarkQuestion]:
    """
    Generate realistic benchmark questions based on customer context.

    Creates questions across different categories and difficulties that
    reflect real-world queries the customer might make.

    Args:
        customer: Customer name
        use_cases: List of use case dicts from extract_use_cases()
        count_range: (min, max) number of questions to generate
        processor: Parallel processor tier

    Returns:
        List of BenchmarkQuestion objects
    """
    min_count, max_count = count_range
    target_count = (min_count + max_count) // 2

    # Calculate distribution
    questions_per_use_case = max(5, target_count // len(use_cases)) if use_cases else target_count

    all_questions = []

    for use_case in use_cases:
        use_case_questions = _generate_questions_for_use_case(
            customer=customer,
            use_case=use_case,
            count=questions_per_use_case,
            processor=processor,
        )
        all_questions.extend(use_case_questions)

    # Ensure we have enough questions
    while len(all_questions) < min_count:
        # Add more questions with varied difficulty
        extra = _generate_extra_questions(customer, min_count - len(all_questions))
        all_questions.extend(extra)

    # Trim if we have too many
    if len(all_questions) > max_count:
        all_questions = all_questions[:max_count]

    # Assign unique IDs
    for i, q in enumerate(all_questions):
        if not q.id or q.id.startswith("temp-"):
            q.id = f"q-{i+1:03d}"

    return all_questions


def _generate_questions_for_use_case(
    customer: str,
    use_case: dict,
    count: int,
    processor: str = "base",
) -> list[BenchmarkQuestion]:
    """Generate questions for a specific use case."""

    name = use_case.get("name", "general")
    description = use_case.get("description", "")
    category_str = use_case.get("category", "research")
    themes = use_case.get("question_themes", [])

    # Map category string to enum
    category_map = {
        "search": QuestionCategory.SEARCH,
        "enrichment": QuestionCategory.ENRICHMENT,
        "research": QuestionCategory.RESEARCH,
    }
    category = category_map.get(category_str, QuestionCategory.RESEARCH)

    # Build question generation prompt
    query = f"""Generate {count} benchmark questions for testing an AI research assistant.

Context:
- Customer: {customer}
- Use Case: {name} - {description}
- Category: {category_str}
- Themes: {', '.join(themes) if themes else 'general business research'}

Requirements:
- Questions should be realistic queries a {customer} employee might ask
- Mix of difficulties: ~30% easy (factual lookups), ~50% medium (multi-step), ~20% hard (complex analysis)
- Questions should be specific enough to have verifiable answers
- Include a mix of question types: factual, list-based, analytical, comparative

For each question, provide:
1. text: The question itself
2. difficulty: "easy", "medium", or "hard"
3. expected_answer_type: "factual", "list", "analysis", "comparison", "summary"
4. evaluation_criteria: List of criteria for evaluating answer quality

Return as a JSON array of question objects."""

    result = parallel_task_quick(query, processor=processor)

    if "error" in result:
        return _fallback_questions(customer, name, category, count)

    output = result.get("output", {})
    raw_questions = _parse_questions(output)

    questions = []
    for i, raw in enumerate(raw_questions[:count]):
        try:
            difficulty = Difficulty(raw.get("difficulty", "medium"))
        except ValueError:
            difficulty = Difficulty.MEDIUM

        questions.append(BenchmarkQuestion(
            id=f"temp-{name}-{i+1:03d}",
            text=raw.get("text", raw.get("question", "")),
            category=category,
            difficulty=difficulty,
            expected_answer_type=raw.get("expected_answer_type", "factual"),
            metadata={"use_case": name, "customer": customer},
            evaluation_criteria=raw.get("evaluation_criteria", []),
        ))

    # Fill with fallback if needed
    while len(questions) < count:
        fallback = _fallback_questions(customer, name, category, count - len(questions))
        questions.extend(fallback)

    return questions


def _parse_questions(output: any) -> list[dict]:
    """Parse questions from API output."""
    if isinstance(output, list):
        return output

    if isinstance(output, dict):
        for key in ["questions", "items", "results", "benchmark_questions"]:
            if key in output and isinstance(output[key], list):
                return output[key]

    if isinstance(output, str):
        try:
            parsed = json.loads(output)
            return _parse_questions(parsed)
        except json.JSONDecodeError:
            pass

    return []


def _fallback_questions(
    customer: str,
    use_case: str,
    category: QuestionCategory,
    count: int,
) -> list[BenchmarkQuestion]:
    """Generate fallback questions when API fails."""
    templates = {
        QuestionCategory.SEARCH: [
            f"Find recent news articles about {customer}",
            f"What are {customer}'s main competitors?",
            f"Find {customer}'s latest product announcements",
            f"What is {customer}'s current market position?",
            f"Find information about {customer}'s leadership team",
        ],
        QuestionCategory.ENRICHMENT: [
            f"What is {customer}'s headquarters location?",
            f"How many employees does {customer} have?",
            f"What is {customer}'s annual revenue?",
            f"List {customer}'s main product categories",
            f"What technologies does {customer} use?",
        ],
        QuestionCategory.RESEARCH: [
            f"Analyze {customer}'s competitive positioning",
            f"What are the main trends affecting {customer}'s industry?",
            f"Compare {customer} to its top 3 competitors",
            f"What growth opportunities exist for {customer}?",
            f"Summarize {customer}'s business strategy",
        ],
    }

    questions = []
    template_list = templates.get(category, templates[QuestionCategory.RESEARCH])

    for i in range(min(count, len(template_list))):
        questions.append(BenchmarkQuestion(
            id=f"temp-fallback-{i+1:03d}",
            text=template_list[i],
            category=category,
            difficulty=Difficulty.MEDIUM,
            expected_answer_type="factual" if category == QuestionCategory.ENRICHMENT else "analysis",
            metadata={"use_case": use_case, "customer": customer, "fallback": True},
        ))

    return questions


def _generate_extra_questions(customer: str, count: int) -> list[BenchmarkQuestion]:
    """Generate extra questions to meet minimum count."""
    extra = []
    categories = list(QuestionCategory)
    difficulties = list(Difficulty)

    for i in range(count):
        cat = categories[i % len(categories)]
        diff = difficulties[i % len(difficulties)]

        extra.append(BenchmarkQuestion(
            id=f"temp-extra-{i+1:03d}",
            text=f"Research question {i+1} about {customer}",
            category=cat,
            difficulty=diff,
            expected_answer_type="factual",
            metadata={"customer": customer, "extra": True},
        ))

    return extra


def validate_benchmark(benchmark: Benchmark) -> tuple[bool, list[str]]:
    """
    Validate a benchmark for quality and coverage.

    Checks:
    - Minimum question count
    - Category distribution
    - Difficulty distribution
    - Question quality (no duplicates, sufficient length)

    Args:
        benchmark: Benchmark to validate

    Returns:
        (is_valid, list of issues)
    """
    issues = []

    # Check question count
    if len(benchmark.questions) < 30:
        issues.append(f"Too few questions: {len(benchmark.questions)} (minimum 30)")

    # Check category distribution
    counts = benchmark.question_counts()
    by_category = counts.get("by_category", {})

    for cat in QuestionCategory:
        if by_category.get(cat.value, 0) < 5:
            issues.append(f"Insufficient {cat.value} questions: {by_category.get(cat.value, 0)} (minimum 5)")

    # Check difficulty distribution
    by_difficulty = counts.get("by_difficulty", {})

    for diff in Difficulty:
        if by_difficulty.get(diff.value, 0) < 3:
            issues.append(f"Insufficient {diff.value} questions: {by_difficulty.get(diff.value, 0)} (minimum 3)")

    # Check for duplicate questions
    texts = [q.text.lower().strip() for q in benchmark.questions]
    if len(texts) != len(set(texts)):
        issues.append("Duplicate questions detected")

    # Check question quality
    short_questions = [q for q in benchmark.questions if len(q.text) < 20]
    if short_questions:
        issues.append(f"{len(short_questions)} questions are too short (< 20 chars)")

    return len(issues) == 0, issues


def create_benchmark(
    customer: str,
    use_case_hint: Optional[str] = None,
    count_range: tuple[int, int] = (30, 70),
    processor: str = "base",
    save: bool = True,
) -> Benchmark:
    """
    Full workflow to create a benchmark for a customer.

    1. Research the customer
    2. Extract use cases
    3. Generate questions
    4. Validate and save

    Args:
        customer: Customer name
        use_case_hint: Optional hint about intended use case
        count_range: (min, max) questions to generate
        processor: Parallel processor tier
        save: Whether to save benchmark to disk

    Returns:
        Benchmark object (saved to projects/benchmarks/{customer}/)
    """
    # Research
    research = research_customer(customer, use_case_hint, processor="core")

    # Extract use cases
    use_cases = extract_use_cases(research)

    # Generate questions
    questions = generate_questions(customer, use_cases, count_range, processor)

    # Create benchmark
    benchmark = Benchmark(
        id=Benchmark.generate_id(),
        customer=customer,
        use_case=use_case_hint or "general",
        questions=questions,
        customer_research=research,
        identified_use_cases=[uc.get("name", "") for uc in use_cases],
        status=BenchmarkStatus.CREATED,
    )

    # Validate
    is_valid, issues = validate_benchmark(benchmark)
    if not is_valid:
        benchmark.metadata["validation_issues"] = issues

    # Save
    if save:
        benchmark.save()

    return benchmark


if __name__ == "__main__":
    # Test the creator
    import sys

    if len(sys.argv) > 1:
        customer = sys.argv[1]
        hint = sys.argv[2] if len(sys.argv) > 2 else None

        print(f"Creating benchmark for: {customer}")
        benchmark = create_benchmark(customer, hint, count_range=(30, 50))

        print(f"Benchmark ID: {benchmark.id}")
        print(f"Questions: {len(benchmark.questions)}")
        print(f"Counts: {benchmark.question_counts()}")

        is_valid, issues = validate_benchmark(benchmark)
        print(f"Valid: {is_valid}")
        if issues:
            print(f"Issues: {issues}")
    else:
        print("Usage: python -m lib.benchmark.creator <customer> [use_case_hint]")
