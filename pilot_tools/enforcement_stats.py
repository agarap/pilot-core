"""
tool: enforcement_stats
description: Query enforcement telemetry statistics and manage event history
parameters:
  action: Action to perform (stats, events, cleanup, score, alert, dashboard)
  days: Number of days to look back (default varies by action)
  event_type: Filter by event type (for events action)
  source: Filter by source module (for events action)
  limit: Maximum number of events to return (for events action, default 20)
  dry_run: Show what would be deleted without deleting (for cleanup action)
  quiet: Only show CRITICAL alerts, suppress warnings (for alert action)
  output: File path to write dashboard output (for dashboard action)
returns: Statistics, event list, cleanup result, effectiveness score, alerts, or markdown dashboard
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from pilot_core.telemetry import EventType, get_event_counts, get_events, cleanup_old_events


def enforcement_stats(
    action: str = "stats",
    days: Optional[int] = None,
    event_type: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 20,
    dry_run: bool = False,
    quiet: bool = False,
    output: Optional[str] = None,
) -> dict:
    """
    Query enforcement telemetry statistics and manage event history.

    Actions:
    - stats: Show event counts by type (default: last 7 days)
    - events: List recent events with filtering (default: last 1 day)
    - cleanup: Remove old events (default: older than 30 days)
    - score: Compute effectiveness score based on event patterns
    - alert: Check thresholds and output warnings/critical alerts
    - dashboard: Generate markdown dashboard report

    Args:
        action: stats, events, cleanup, score, alert, or dashboard
        days: Time window in days (default: 7 for stats/score/dashboard, 1 for events, 30 for cleanup)
        event_type: Filter by event type (events action only)
        source: Filter by source module (events action only)
        limit: Max events to return (events action only, default 20)
        dry_run: Preview cleanup without deleting (cleanup action only)
        quiet: Only show CRITICAL alerts, suppress warnings (alert action only)
        output: File path to write dashboard (dashboard action only)

    Returns:
        Dict with results based on action
    """
    if action == "stats":
        return _stats(days if days is not None else 7)
    elif action == "events":
        return _events(
            days=days if days is not None else 1,
            event_type=event_type,
            source=source,
            limit=limit,
        )
    elif action == "cleanup":
        return _cleanup(days=days if days is not None else 30, dry_run=dry_run)
    elif action == "score":
        return _score()
    elif action == "alert":
        return _alert(quiet=quiet)
    elif action == "dashboard":
        return _dashboard(days=days if days is not None else 7, output=output)
    else:
        return {"error": f"Unknown action: {action}. Use: stats, events, cleanup, score, alert, dashboard"}


def _stats(days: int) -> dict:
    """Get event counts by type."""
    counts = get_event_counts(since_days=days)
    total = sum(counts.values())

    return {
        "action": "stats",
        "days": days,
        "total_events": total,
        "by_type": counts,
        "event_types": list(EventType.__members__.keys()),
    }


def _events(
    days: int,
    event_type: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """List recent events with filtering."""
    # Validate event_type if provided
    type_filter = None
    if event_type:
        # Try to find matching EventType
        try:
            type_filter = EventType(event_type)
        except ValueError:
            # Try uppercase version
            try:
                type_filter = EventType[event_type.upper()]
            except KeyError:
                return {
                    "error": f"Unknown event type: {event_type}",
                    "valid_types": [e.value for e in EventType],
                }

    # Get events from telemetry
    events = get_events(since_days=days, event_type=type_filter)

    # Apply source filter (not supported by get_events directly)
    if source:
        events = [e for e in events if source.lower() in e.get("source", "").lower()]

    # Sort by timestamp descending (most recent first)
    events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    # Apply limit
    events = events[:limit]

    # Format events for display
    formatted = []
    for event in events:
        formatted.append({
            "timestamp": event.get("timestamp", ""),
            "type": event.get("event_type", ""),
            "source": event.get("source", ""),
            "details": event.get("details", {}),
        })

    return {
        "action": "events",
        "days": days,
        "filters": {
            "event_type": event_type,
            "source": source,
            "limit": limit,
        },
        "count": len(formatted),
        "events": formatted,
    }


def _cleanup(days: int, dry_run: bool) -> dict:
    """Remove old events."""
    if dry_run:
        # Count events that would be removed
        all_events = get_events(since_days=None)
        cutoff = datetime.now().timestamp() - (days * 24 * 60 * 60)

        would_remove = 0
        would_keep = 0
        for event in all_events:
            try:
                event_time = datetime.fromisoformat(event.get("timestamp", ""))
                if event_time.timestamp() < cutoff:
                    would_remove += 1
                else:
                    would_keep += 1
            except (ValueError, AttributeError):
                would_keep += 1  # Keep malformed events

        return {
            "action": "cleanup",
            "dry_run": True,
            "retention_days": days,
            "would_remove": would_remove,
            "would_keep": would_keep,
            "message": f"Would remove {would_remove} events older than {days} days",
        }
    else:
        removed = cleanup_old_events(days=days)
        return {
            "action": "cleanup",
            "dry_run": False,
            "retention_days": days,
            "removed": removed,
            "message": f"Removed {removed} events older than {days} days",
        }


def _compute_trend(current_count: int, previous_count: int) -> str:
    """
    Compute trend direction comparing current to previous period.

    Returns: 'increasing', 'decreasing', or 'stable'
    """
    if previous_count == 0:
        if current_count == 0:
            return "stable"
        return "increasing"

    # Calculate percentage change
    change_pct = ((current_count - previous_count) / previous_count) * 100

    # Use 20% threshold for trend detection
    if change_pct > 20:
        return "increasing"
    elif change_pct < -20:
        return "decreasing"
    return "stable"


def _score() -> dict:
    """
    Compute effectiveness score based on event patterns.

    Uses 7-day windows to compare current week vs previous week.
    Scoring based on thresholds from enforcement_stats.yaml:
    - excellent: violation_detected < 2/week + import_blocked decreasing + no bypasses
    - good: violation_detected < 5/week + stable/decreasing blocked + no bypasses
    - concerning: violation_detected 5-10/week OR increasing blocked OR bypasses > 0
    - critical: violation_detected > 10/week OR bypasses > 1
    """
    # Get counts for current week (last 7 days)
    current_counts = get_event_counts(since_days=7)

    # Get counts for previous week (8-14 days ago)
    # We get 14 days and subtract current week
    two_week_counts = get_event_counts(since_days=14)
    previous_counts = {
        k: two_week_counts.get(k, 0) - current_counts.get(k, 0)
        for k in set(two_week_counts.keys()) | set(current_counts.keys())
    }

    # Extract key metrics
    violations_current = current_counts.get("violation_detected", 0)
    violations_previous = previous_counts.get("violation_detected", 0)

    blocked_current = current_counts.get("import_blocked", 0)
    blocked_previous = previous_counts.get("import_blocked", 0)

    bypasses_current = current_counts.get("commit_review_bypassed", 0)
    bypasses_previous = previous_counts.get("commit_review_bypassed", 0)

    # Compute trends
    violations_trend = _compute_trend(violations_current, violations_previous)
    blocked_trend = _compute_trend(blocked_current, blocked_previous)
    bypasses_trend = _compute_trend(bypasses_current, bypasses_previous)

    # Determine rating based on criteria from enforcement_stats.yaml
    # Critical: violation_detected > 10/week OR bypasses > 1
    if violations_current > 10 or bypasses_current > 1:
        rating = "critical"
        description = "Enforcement system failure"
    # Concerning: violation_detected 5-10/week OR increasing blocked OR bypasses > 0
    elif (
        5 <= violations_current <= 10
        or blocked_trend == "increasing"
        or bypasses_current > 0
    ):
        rating = "concerning"
        description = "Enforcement needs attention"
    # Excellent: violation_detected < 2/week + import_blocked decreasing + no bypasses
    elif (
        violations_current < 2
        and blocked_trend in ("decreasing", "stable")
        and bypasses_current == 0
    ):
        # Additional check: blocked should be decreasing for "excellent"
        if blocked_trend == "decreasing" or blocked_current == 0:
            rating = "excellent"
            description = "Enforcement is working optimally"
        else:
            rating = "good"
            description = "Enforcement is working with minor issues"
    # Good: violation_detected < 5/week + stable/decreasing blocked + no bypasses
    elif (
        violations_current < 5
        and blocked_trend in ("decreasing", "stable")
        and bypasses_current == 0
    ):
        rating = "good"
        description = "Enforcement is working with minor issues"
    else:
        # Default to concerning if none of the above match
        rating = "concerning"
        description = "Enforcement needs attention"

    # Build score breakdown
    breakdown = {
        "violations": {
            "current_week": violations_current,
            "previous_week": violations_previous,
            "trend": violations_trend,
            "threshold": "<5/week for good, <2/week for excellent",
        },
        "import_blocked": {
            "current_week": blocked_current,
            "previous_week": blocked_previous,
            "trend": blocked_trend,
            "threshold": "decreasing is good",
        },
        "bypasses": {
            "current_week": bypasses_current,
            "previous_week": bypasses_previous,
            "trend": bypasses_trend,
            "threshold": "0 is required for good/excellent",
        },
    }

    return {
        "action": "score",
        "rating": rating,
        "description": description,
        "breakdown": breakdown,
        "period": {
            "current_week": "last 7 days",
            "previous_week": "8-14 days ago",
        },
        "total_events_current": sum(current_counts.values()),
        "total_events_previous": sum(previous_counts.values()),
    }


def _alert(quiet: bool = False) -> dict:
    """
    Check thresholds and generate alerts.

    Thresholds (from data/enforcement_stats.yaml):
    - violation_detected > 10/week = CRITICAL
    - violation_detected > 5/week = WARNING
    - commit_review_bypassed > 0 = CRITICAL
    - import_blocked increasing significantly = WARNING

    Args:
        quiet: Only include CRITICAL alerts, suppress warnings

    Returns:
        Dict with alerts list, has_critical flag, and has_warnings flag
    """
    # Get counts for current week (last 7 days)
    current_counts = get_event_counts(since_days=7)

    # Get counts for previous week (8-14 days ago)
    two_week_counts = get_event_counts(since_days=14)
    previous_counts = {
        k: two_week_counts.get(k, 0) - current_counts.get(k, 0)
        for k in set(two_week_counts.keys()) | set(current_counts.keys())
    }

    # Extract key metrics
    violations_current = current_counts.get("violation_detected", 0)
    blocked_current = current_counts.get("import_blocked", 0)
    blocked_previous = previous_counts.get("import_blocked", 0)
    bypasses_current = current_counts.get("commit_review_bypassed", 0)

    # Compute blocked trend
    blocked_trend = _compute_trend(blocked_current, blocked_previous)

    alerts = []

    # Check: commit_review_bypassed > 0 = CRITICAL
    if bypasses_current > 0:
        alerts.append({
            "level": "CRITICAL",
            "metric": "commit_review_bypassed",
            "message": f"Git review bypassed {bypasses_current} time(s) this week",
            "value": bypasses_current,
            "threshold": 0,
        })

    # Check: violation_detected > 10/week = CRITICAL
    if violations_current > 10:
        alerts.append({
            "level": "CRITICAL",
            "metric": "violation_detected",
            "message": f"Violations exceeded critical threshold: {violations_current}/week (threshold: 10)",
            "value": violations_current,
            "threshold": 10,
        })
    # Check: violation_detected > 5/week = WARNING
    elif violations_current > 5:
        alerts.append({
            "level": "WARNING",
            "metric": "violation_detected",
            "message": f"Violations exceeded warning threshold: {violations_current}/week (threshold: 5)",
            "value": violations_current,
            "threshold": 5,
        })

    # Check: import_blocked increasing significantly = WARNING
    # "Significantly" = increasing trend (>20% increase)
    if blocked_trend == "increasing":
        alerts.append({
            "level": "WARNING",
            "metric": "import_blocked",
            "message": f"Import blocks increasing: {blocked_previous} -> {blocked_current} this week",
            "value": blocked_current,
            "previous": blocked_previous,
        })

    # Filter if quiet mode
    if quiet:
        alerts = [a for a in alerts if a["level"] == "CRITICAL"]

    has_critical = any(a["level"] == "CRITICAL" for a in alerts)
    has_warnings = any(a["level"] == "WARNING" for a in alerts)

    return {
        "action": "alert",
        "alerts": alerts,
        "has_critical": has_critical,
        "has_warnings": has_warnings,
        "quiet_mode": quiet,
        "status": "critical" if has_critical else ("warning" if has_warnings else "ok"),
        "metrics": {
            "violation_detected": violations_current,
            "commit_review_bypassed": bypasses_current,
            "import_blocked": blocked_current,
            "import_blocked_trend": blocked_trend,
        },
    }


def _dashboard(days: int = 7, output: Optional[str] = None) -> dict:
    """
    Generate a markdown dashboard report combining stats, score, and alerts.

    Args:
        days: Time window for stats (default: 7)
        output: Optional file path to write the dashboard

    Returns:
        Dict with markdown content and metadata
    """
    # Gather data from other functions
    stats_result = _stats(days)
    score_result = _score()
    alert_result = _alert(quiet=False)

    # Build markdown content
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []

    # Header
    lines.append("# Enforcement Telemetry Dashboard")
    lines.append("")
    lines.append(f"**Generated:** {timestamp}")
    lines.append("")

    # Effectiveness Score Section
    rating = score_result.get("rating", "unknown")
    description = score_result.get("description", "")

    # Rating emoji indicators
    rating_emoji = {
        "excellent": "\u2705",  # green check
        "good": "\U0001F7E2",  # green circle
        "concerning": "\u26A0\uFE0F",  # warning
        "critical": "\U0001F534",  # red circle
    }
    emoji = rating_emoji.get(rating, "\u2753")  # question mark fallback

    lines.append("## Effectiveness Score")
    lines.append("")
    lines.append(f"{emoji} **Rating:** {rating.upper()}")
    lines.append("")
    lines.append(f"> {description}")
    lines.append("")

    # Trend analysis
    breakdown = score_result.get("breakdown", {})
    if breakdown:
        lines.append("### Trend Analysis")
        lines.append("")
        lines.append("| Metric | Current | Previous | Trend |")
        lines.append("|--------|---------|----------|-------|")

        trend_emoji = {
            "increasing": "\u2B06\uFE0F",  # up arrow
            "decreasing": "\u2B07\uFE0F",  # down arrow
            "stable": "\u27A1\uFE0F",  # right arrow
        }

        for metric_name, data in breakdown.items():
            display_name = metric_name.replace("_", " ").title()
            current = data.get("current_week", 0)
            previous = data.get("previous_week", 0)
            trend = data.get("trend", "stable")
            t_emoji = trend_emoji.get(trend, "")
            lines.append(f"| {display_name} | {current} | {previous} | {t_emoji} {trend} |")

        lines.append("")

    # Alerts Section
    alerts = alert_result.get("alerts", [])
    if alerts:
        lines.append("## Active Alerts")
        lines.append("")

        for alert in alerts:
            level = alert["level"]
            message = alert["message"]
            level_emoji = "\U0001F534" if level == "CRITICAL" else "\U0001F7E1"  # red or yellow
            lines.append(f"- {level_emoji} **{level}:** {message}")

        lines.append("")
    else:
        lines.append("## Active Alerts")
        lines.append("")
        lines.append("\u2705 No active alerts")
        lines.append("")

    # Event Counts Section
    lines.append(f"## Event Counts (Last {days} Days)")
    lines.append("")

    by_type = stats_result.get("by_type", {})
    if by_type:
        lines.append("| Event Type | Count |")
        lines.append("|------------|-------|")

        for event_type, count in sorted(by_type.items()):
            lines.append(f"| {event_type} | {count} |")

        lines.append("")
        lines.append(f"**Total Events:** {stats_result.get('total_events', 0)}")
        lines.append("")
    else:
        lines.append("*No events recorded in this period.*")
        lines.append("")

    # Period Information
    period = score_result.get("period", {})
    lines.append("---")
    lines.append("")
    lines.append(f"*Period: {period.get('current_week', 'last 7 days')} compared to {period.get('previous_week', 'previous 7 days')}*")

    markdown_content = "\n".join(lines)

    # Write to file if output path provided
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown_content)

    return {
        "action": "dashboard",
        "markdown": markdown_content,
        "output_file": output,
        "stats_days": days,
        "rating": rating,
        "has_alerts": len(alerts) > 0,
        "total_events": stats_result.get("total_events", 0),
    }


def format_alert_output(result: dict) -> str:
    """Format alert result as plain text for terminal."""
    alerts = result.get("alerts", [])

    if not alerts:
        return ""  # Silent output when all OK

    lines = []
    for alert in alerts:
        level = alert["level"]
        message = alert["message"]
        lines.append(f"[{level}] {message}")

    return "\n".join(lines)


def format_stats_table(result: dict) -> str:
    """Format stats result as a readable table."""
    lines = [
        f"Enforcement Stats (last {result['days']} days)",
        "=" * 45,
        "",
    ]

    by_type = result.get("by_type", {})
    if by_type:
        # Find max width for type names
        max_width = max(len(t) for t in by_type.keys()) if by_type else 20

        lines.append(f"{'Event Type':<{max_width}}  {'Count':>8}")
        lines.append("-" * (max_width + 10))

        for event_type, count in sorted(by_type.items()):
            lines.append(f"{event_type:<{max_width}}  {count:>8}")

        lines.append("-" * (max_width + 10))
        lines.append(f"{'TOTAL':<{max_width}}  {result['total_events']:>8}")
    else:
        lines.append("No events recorded")

    return "\n".join(lines)


def format_events_table(result: dict) -> str:
    """Format events result as a readable table."""
    lines = [
        f"Recent Events (last {result['days']} day(s))",
        "=" * 80,
        "",
    ]

    filters = result.get("filters", {})
    if filters.get("event_type") or filters.get("source"):
        filter_parts = []
        if filters.get("event_type"):
            filter_parts.append(f"type={filters['event_type']}")
        if filters.get("source"):
            filter_parts.append(f"source={filters['source']}")
        lines.append(f"Filters: {', '.join(filter_parts)}")
        lines.append("")

    events = result.get("events", [])
    if events:
        lines.append(f"{'Timestamp':<26}  {'Type':<25}  {'Source':<20}")
        lines.append("-" * 80)

        for event in events:
            ts = event.get("timestamp", "")[:26]  # Truncate microseconds
            etype = event.get("type", "")[:25]
            src = event.get("source", "")[:20]
            lines.append(f"{ts:<26}  {etype:<25}  {src:<20}")

            # Show details if present
            details = event.get("details", {})
            if details:
                detail_str = json.dumps(details)
                if len(detail_str) > 70:
                    detail_str = detail_str[:67] + "..."
                lines.append(f"  -> {detail_str}")

        lines.append("")
        lines.append(f"Showing {result['count']} event(s)")
    else:
        lines.append("No events found")

    return "\n".join(lines)


def format_cleanup_result(result: dict) -> str:
    """Format cleanup result as readable text."""
    lines = [
        f"Cleanup (retention: {result['retention_days']} days)",
        "=" * 45,
        "",
    ]

    if result.get("dry_run"):
        lines.append("[DRY RUN - no changes made]")
        lines.append("")
        lines.append(f"Events to remove: {result.get('would_remove', 0)}")
        lines.append(f"Events to keep:   {result.get('would_keep', 0)}")
    else:
        lines.append(f"Events removed: {result.get('removed', 0)}")

    return "\n".join(lines)


def format_score_table(result: dict) -> str:
    """Format effectiveness score as a readable table."""
    rating = result.get("rating", "unknown").upper()
    description = result.get("description", "")

    # Rating indicators
    rating_symbols = {
        "EXCELLENT": "[+]",
        "GOOD": "[~]",
        "CONCERNING": "[!]",
        "CRITICAL": "[X]",
    }
    symbol = rating_symbols.get(rating, "[?]")

    lines = [
        "Enforcement Effectiveness Score",
        "=" * 55,
        "",
        f"  {symbol} Overall Rating: {rating}",
        f"      {description}",
        "",
        "Score Breakdown",
        "-" * 55,
        "",
    ]

    breakdown = result.get("breakdown", {})

    # Format each metric
    for metric_name, data in breakdown.items():
        display_name = metric_name.replace("_", " ").title()
        current = data.get("current_week", 0)
        previous = data.get("previous_week", 0)
        trend = data.get("trend", "stable")
        threshold = data.get("threshold", "")

        # Trend arrow
        trend_arrows = {
            "increasing": "^",
            "decreasing": "v",
            "stable": "-",
        }
        arrow = trend_arrows.get(trend, "?")

        lines.append(f"  {display_name}:")
        lines.append(f"    Current week:  {current:>4}  [{arrow}] {trend}")
        lines.append(f"    Previous week: {previous:>4}")
        lines.append(f"    Threshold:     {threshold}")
        lines.append("")

    # Period info
    period = result.get("period", {})
    lines.append("-" * 55)
    lines.append(f"Period: {period.get('current_week', 'N/A')} vs {period.get('previous_week', 'N/A')}")
    lines.append(f"Total events: {result.get('total_events_current', 0)} (current) / {result.get('total_events_previous', 0)} (previous)")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    # Check for MCP-style JSON input first
    if len(sys.argv) == 2 and sys.argv[1].startswith("{"):
        try:
            args = json.loads(sys.argv[1])
            result = enforcement_stats(**args)
            print(json.dumps(result, indent=2, default=str))
            sys.exit(0)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": "Invalid JSON", "details": str(e)}))
            sys.exit(1)

    # Standard argparse CLI
    parser = argparse.ArgumentParser(
        description="Query enforcement telemetry statistics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show stats for last 7 days
  uv run python tools/enforcement_stats.py stats

  # Show stats for last 30 days
  uv run python tools/enforcement_stats.py stats --days 30

  # List recent events
  uv run python tools/enforcement_stats.py events

  # List events filtered by type
  uv run python tools/enforcement_stats.py events --type import_blocked

  # List events filtered by source
  uv run python tools/enforcement_stats.py events --source guards.py

  # Preview cleanup
  uv run python tools/enforcement_stats.py cleanup --dry-run

  # Cleanup events older than 60 days
  uv run python tools/enforcement_stats.py cleanup --days 60

  # Show effectiveness score
  uv run python tools/enforcement_stats.py score

  # Show effectiveness score as JSON
  uv run python tools/enforcement_stats.py score --json

  # Check threshold alerts
  uv run python tools/enforcement_stats.py alert

  # Check only critical alerts (for cron/scripting)
  uv run python tools/enforcement_stats.py alert --quiet

  # Generate markdown dashboard
  uv run python tools/enforcement_stats.py dashboard

  # Generate dashboard and save to file
  uv run python tools/enforcement_stats.py dashboard --output docs/dashboard.md

  # MCP-style JSON input
  uv run python tools/enforcement_stats.py '{"action": "stats", "days": 14}'
  uv run python tools/enforcement_stats.py '{"action": "score"}'
  uv run python tools/enforcement_stats.py '{"action": "alert", "quiet": true}'
  uv run python tools/enforcement_stats.py '{"action": "dashboard"}'
  uv run python tools/enforcement_stats.py '{"action": "dashboard", "output": "docs/dashboard.md"}'
""",
    )

    subparsers = parser.add_subparsers(dest="action", help="Action to perform")

    # stats subcommand
    stats_parser = subparsers.add_parser("stats", help="Show event counts by type")
    stats_parser.add_argument(
        "--days", "-d", type=int, default=7, help="Days to look back (default: 7)"
    )
    stats_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )

    # events subcommand
    events_parser = subparsers.add_parser("events", help="List recent events")
    events_parser.add_argument(
        "--days", "-d", type=int, default=1, help="Days to look back (default: 1)"
    )
    events_parser.add_argument(
        "--type", "-t", dest="event_type", help="Filter by event type"
    )
    events_parser.add_argument(
        "--source", "-s", help="Filter by source module"
    )
    events_parser.add_argument(
        "--limit", "-n", type=int, default=20, help="Max events to show (default: 20)"
    )
    events_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )

    # cleanup subcommand
    cleanup_parser = subparsers.add_parser("cleanup", help="Remove old events")
    cleanup_parser.add_argument(
        "--days", "-d", type=int, default=30, help="Retention period in days (default: 30)"
    )
    cleanup_parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be deleted without deleting"
    )
    cleanup_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )

    # score subcommand
    score_parser = subparsers.add_parser("score", help="Show effectiveness score")
    score_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )

    # alert subcommand
    alert_parser = subparsers.add_parser("alert", help="Check thresholds and output warnings")
    alert_parser.add_argument(
        "--quiet", "-q", action="store_true", help="Only show CRITICAL alerts"
    )
    alert_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )

    # dashboard subcommand
    dashboard_parser = subparsers.add_parser("dashboard", help="Generate markdown dashboard report")
    dashboard_parser.add_argument(
        "--days", "-d", type=int, default=7, help="Days to look back for stats (default: 7)"
    )
    dashboard_parser.add_argument(
        "--output", "-o", help="File path to write dashboard (default: stdout)"
    )
    dashboard_parser.add_argument(
        "--json", action="store_true", help="Output as JSON (includes markdown in 'markdown' field)"
    )

    args = parser.parse_args()

    if not args.action:
        parser.print_help()
        sys.exit(1)

    # Build kwargs based on action
    kwargs = {"action": args.action}

    # Add days for actions that use it
    if args.action in ("stats", "events", "cleanup", "dashboard"):
        kwargs["days"] = args.days

    if args.action == "events":
        kwargs["event_type"] = args.event_type
        kwargs["source"] = args.source
        kwargs["limit"] = args.limit
    elif args.action == "cleanup":
        kwargs["dry_run"] = args.dry_run
    elif args.action == "alert":
        kwargs["quiet"] = args.quiet
    elif args.action == "dashboard":
        kwargs["output"] = args.output

    result = enforcement_stats(**kwargs)

    # Output format
    output_json = getattr(args, "json", False)

    if output_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        if "error" in result:
            print(f"Error: {result['error']}")
            if "valid_types" in result:
                print(f"Valid types: {', '.join(result['valid_types'])}")
            sys.exit(1)

        if args.action == "stats":
            print(format_stats_table(result))
        elif args.action == "events":
            print(format_events_table(result))
        elif args.action == "cleanup":
            print(format_cleanup_result(result))
        elif args.action == "score":
            print(format_score_table(result))
        elif args.action == "alert":
            output = format_alert_output(result)
            if output:
                print(output)
            # Exit code 1 if any alerts (critical or warning)
            if result.get("has_critical") or result.get("has_warnings"):
                sys.exit(1)
        elif args.action == "dashboard":
            # Print markdown to stdout unless --output was specified
            if result.get("output_file"):
                print(f"Dashboard written to: {result['output_file']}", file=sys.stderr)
            else:
                print(result.get("markdown", ""))
