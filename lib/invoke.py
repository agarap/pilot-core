"""
Invoke SDK-based agents from Pilot.

This module bridges Claude Code (where Pilot runs natively) with SDK-based
agents (builder, web-researcher, git-reviewer) defined in agents/*.yaml.

Usage from Pilot (via Bash):
    uv run python -m lib.invoke builder '{"task": "Create a new tool"}'

Usage programmatically:
    from lib.invoke import invoke_agent
    result = await invoke_agent("builder", "Create a new tool")

The invocation:
1. Loads agent config from agents/<name>.yaml
2. Builds context (system prompt + rules + agent prompt)
3. Executes via Claude Code SDK
4. Returns structured output with files changed

Each invocation is a separate Claude API call, providing:
- Isolated context per agent
- Clear audit trail
- Different model selection per agent
"""

import asyncio
import json
import logging
import os
import random
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from claude_code_sdk import (
    query,
    ClaudeCodeOptions,
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)

# Retry configuration for rate limits
# Start at 5 seconds, exponential backoff: 5s, 10s, 20s, 40s, 80s, 160s, 320s (capped)
INITIAL_BACKOFF_SECONDS = 5.0
MAX_BACKOFF_SECONDS = 320.0
JITTER_FACTOR = 0.25  # +/- 25% jitter
MAX_RETRY_ATTEMPTS = 10  # For logging purposes, but rate limits retry forever

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.context import (
    build_context,
    load_agent_config,
    get_current_branch,
)
from lib.progress import (
    ProgressFile,
    ProgressStatus,
    write_progress,
    update_heartbeat,
    mark_completed,
    mark_failed,
)
from lib.log import log_agent
from lib.run import Run
from tools.context import context as gather_context
from lib.search import get_all_rules
from lib.violation_watcher import start_watcher
from lib.repo_search import context_for as repo_search_context

# Start violation watcher at module load time
# Detects Task tool violations in real-time during agent invocations
start_watcher()

# Module logger
logger = logging.getLogger("pilot.invoke")

# Recursion depth limit to prevent runaway agent spawning
MAX_AGENT_DEPTH = 4

# Tools that modify files
FILE_MODIFYING_TOOLS = {'Write', 'Edit', 'NotebookEdit'}

# Pre-invocation guard: Dangerous patterns to block
DANGEROUS_PATTERNS = [
    r'rm\s+-rf\s+/',           # rm -rf /
    r'dd\s+if=',               # dd if= (disk destroyer)
    r'mkfs\.',                 # mkfs (format filesystem)
    r':\(\)\{\s*:\|:&\s*\};:', # Fork bomb
    r'>\s*/dev/sd[a-z]',       # Write to disk device
    r'chmod\s+-R\s+777\s+/',   # Dangerous chmod
    r'wget\s+.*\|\s*sh',       # wget pipe to shell
    r'curl\s+.*\|\s*bash',     # curl pipe to bash
]

# Pre-invocation guard: Task keywords that suggest misrouted tasks
AGENT_ROUTING_HINTS = {
    'research': 'web-researcher',
    'search': 'web-researcher',
    'find information': 'web-researcher',
    'look up': 'web-researcher',
    'web': 'web-researcher',
    'review': 'git-reviewer',
    'commit': 'git-reviewer',
    'analyze': 'academic-researcher',
    'hypothesis': 'academic-researcher',
    'synthesize': 'academic-researcher',
}


def _has_file_changes(tool_uses: list) -> bool:
    """Check if any tool uses indicate file modifications."""
    return any(t.get('tool') in FILE_MODIFYING_TOOLS for t in tool_uses)


class PreTaskHookError(Exception):
    """Raised when a pre_task hook fails, aborting agent execution."""
    pass


def _process_pre_task_hooks(config: dict, task: str) -> None:
    """
    Process pre_task hooks defined in agent config.

    Runs synchronously before agent execution. If any hook fails,
    raises PreTaskHookError to abort the invocation.

    Args:
        config: Agent configuration dict
        task: The task description being executed

    Raises:
        PreTaskHookError: If any validation hook fails
    """
    hooks = config.get('hooks', {})
    pre_task_hooks = hooks.get('pre_task', [])

    if not pre_task_hooks:
        return

    logger = logging.getLogger('pilot.invoke')

    for action in pre_task_hooks:
        if action == 'validate_config':
            # Check config has required fields
            required_fields = ['name', 'type', 'prompt']
            missing = [f for f in required_fields if not config.get(f)]
            if missing:
                raise PreTaskHookError(
                    f"validate_config failed: missing required fields: {missing}"
                )
            logger.debug(f'pre_task hook validate_config: passed')

        elif action == 'check_deps':
            # Placeholder for dependency checking - log for now
            logger.debug(f'pre_task hook check_deps: placeholder (full implementation later)')

        elif action == 'clear_cache':
            # Placeholder for cache clearing - log for now
            logger.debug(f'pre_task hook clear_cache: placeholder (full implementation later)')

        elif action == 'log_start':
            # Log execution start with task details
            agent_name = config.get('name', 'unknown')
            logger.info(f'Agent "{agent_name}" starting task: {task[:100]}{"..." if len(task) > 100 else ""}')

        else:
            logger.warning(f'Unknown pre_task hook action: {action}')


async def _process_post_task_hooks(
    config: dict,
    tool_uses: list,
    task: str,
    success: bool,
    run_id: Optional[str] = None,
    verbose: bool = False,
) -> None:
    """
    Process post_task hooks defined in agent config.

    Fire-and-forget: errors are logged but don't fail the main result.
    """
    if not success:
        return

    hooks = config.get('hooks', {})
    post_task_hooks = hooks.get('post_task', [])

    if not post_task_hooks:
        return

    logger = logging.getLogger('pilot.invoke')

    for action in post_task_hooks:
        # hooks.post_task is a list of action strings (e.g., ['run_verifier'])
        if action == 'run_verifier':
            # Only run verifier if file changes were made
            if not _has_file_changes(tool_uses):
                logger.debug('Skipping verifier hook: no file changes detected')
                continue

            try:
                logger.info(f'Running post_task hook: {action}')
                verifier_task = f"Verify the changes made for task: {task}"
                # Recursive call - depth limit will protect against runaway
                await invoke_agent('verifier', verifier_task, run_id=run_id, verbose=verbose)
            except Exception as e:
                # Fire-and-forget: log but don't fail
                logger.warning(f'Post-task hook {action} failed: {e}')
        else:
            logger.warning(f'Unknown post_task hook action: {action}')


def check_task_legitimacy(task: str, agent_name: str) -> dict:
    """Pre-invocation guard to block dangerous commands and warn about misrouted tasks.

    Args:
        task: The task description being sent to the agent
        agent_name: Name of the agent being invoked

    Returns:
        dict with:
            - error: True if dangerous pattern found (BLOCKS invocation)
            - warning: True if task appears misrouted (logs warning but continues)
            - message: Description of the issue
            - pattern: The dangerous pattern matched (if error)
            - suggested_agent: The recommended agent (if warning)

        Empty dict if no issues found.
    """
    task_lower = task.lower()

    # Check for dangerous patterns - these BLOCK invocation
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, task, re.IGNORECASE):
            return {
                'error': True,
                'message': f"Task contains dangerous pattern: '{pattern}'. Invocation blocked for safety.",
                'pattern': pattern,
            }

    # Check for misrouted tasks - these generate warnings but don't block
    for keyword, suggested_agent in AGENT_ROUTING_HINTS.items():
        if keyword in task_lower and agent_name != suggested_agent:
            # Don't warn if the suggested agent is a substring of the current agent
            # e.g., "web-researcher" tasks going to "web-researcher" shouldn't warn
            if suggested_agent != agent_name:
                return {
                    'warning': True,
                    'message': (
                        f"Task contains '{keyword}' but is being sent to @{agent_name}. "
                        f"Consider using @{suggested_agent} instead."
                    ),
                    'suggested_agent': suggested_agent,
                }

    return {}


def is_rate_limit_error(error: Exception) -> bool:
    """Check if an exception is a rate limit error."""
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()

    rate_limit_indicators = [
        "429",
        "rate limit",
        "rate_limit",
        "ratelimit",
        "overloaded",
        "too many requests",
        "capacity",
        "throttl",
    ]

    return any(indicator in error_str or indicator in error_type
               for indicator in rate_limit_indicators)


def extract_retry_after(error: Exception) -> Optional[float]:
    """Extract Retry-After value from error message if present."""
    error_str = str(error)

    # Look for patterns like "retry after 30 seconds" or "Retry-After: 30"
    patterns = [
        r"retry[- ]?after[:\s]+(\d+(?:\.\d+)?)",
        r"try again in (\d+(?:\.\d+)?)\s*(?:seconds?)?",
        r"wait (\d+(?:\.\d+)?)\s*(?:seconds?)?",
    ]

    for pattern in patterns:
        match = re.search(pattern, error_str, re.IGNORECASE)
        if match:
            return float(match.group(1))

    return None


def calculate_backoff(attempt: int, retry_after: Optional[float] = None) -> float:
    """Calculate backoff time with exponential increase and jitter."""
    if retry_after is not None:
        # Respect Retry-After but still add small jitter
        base = min(retry_after, MAX_BACKOFF_SECONDS)
    else:
        # Exponential backoff: 1, 2, 4, 8, 16, 32, 60, 60, ...
        base = min(INITIAL_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)

    # Add jitter to prevent thundering herd
    jitter = base * JITTER_FACTOR * (2 * random.random() - 1)
    return max(0.1, base + jitter)


# Model mapping - agents can specify model in their YAML
MODEL_MAP = {
    "opus": "claude-opus-4-5-20251101",
    "sonnet": "claude-sonnet-4-5-20250929",
    "haiku": "claude-3-5-haiku-20241022",
}


def _format_context_for_prompt(ctx: dict) -> str:
    """Format gathered context as a prompt section."""
    if not ctx:
        return ''

    sections = []

    if ctx.get('keyword_matches'):
        items = ctx['keyword_matches'][:3]
        if items:
            sections.append('## Related files from index')
            for item in items:
                sections.append(f"- {item.get('path', item.get('name', 'unknown'))}")

    if ctx.get('relevant_rules'):
        rules = ctx['relevant_rules'][:2]
        if rules:
            sections.append('## Relevant rules')
            for rule in rules:
                sections.append(f"- {rule.get('name', 'unknown')}: {rule.get('description', '')[:100]}")

    if not sections:
        return ''

    return '\n\n<gathered-context>\n' + '\n'.join(sections) + '\n</gathered-context>\n\n'


def _extract_project_from_task(task: str) -> Optional[str]:
    """Extract project name from task if it references projects/<project>/.

    Args:
        task: The task description

    Returns:
        Project name if found, None otherwise.
    """
    # Look for projects/<project>/ pattern in task
    match = re.search(r'projects/([^/\s]+)/', task)
    if match:
        project = match.group(1)
        # Skip namespace directories - those have different validation
        if project not in ('work', 'personal'):
            return project
    return None


def _create_delegation_manifest(
    agent_name: str,
    task: str,
    run_id: Optional[str],
) -> Optional[Path]:
    """Create a run manifest to track delegation.

    Only creates manifests when a project context is detected in the task.
    Manifests are stored in projects/<project>/.runs/ directory.

    Args:
        agent_name: Name of the agent that was invoked
        task: The task description
        run_id: Optional run ID

    Returns:
        Path to created manifest, or None if no project context.
    """
    import yaml

    project = _extract_project_from_task(task)
    if not project:
        return None

    # Create .runs directory if needed
    runs_dir = Path("projects") / project / ".runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Generate manifest filename
    timestamp = datetime.now()
    run_id_str = run_id or f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{agent_name[:8]}"
    safe_task = task[:30].replace(" ", "_").replace("/", "-").replace("'", "").replace('"', "")
    filename = f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{safe_task}.yaml"
    manifest_path = runs_dir / filename

    # Build manifest content
    manifest = {
        "agent": agent_name,
        "run_id": run_id_str,
        "timestamp": timestamp.isoformat(),
        "task": task[:200],  # Truncate long tasks
        "files_modified": [],  # Initially empty, tracked by other mechanisms
    }

    with open(manifest_path, "w") as f:
        yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)

    return manifest_path


def _process_context_injection(config: dict, task: str) -> str:
    """
    Process context_injection section from agent config.

    Supports injection types:
    - rules: List of rule names to inject (from system/rules/)
    - decisions: List of decision IDs to inject (from knowledge/decisions/)
    - files: List of file glob patterns to always include
    - auto: Use context.py to auto-detect relevant context

    Args:
        config: Agent configuration dict
        task: The task description (used for 'auto' mode)

    Returns:
        Formatted context string to prepend to task
    """
    injection_config = config.get('context_injection')
    if not injection_config:
        return ''

    logger = logging.getLogger('pilot.invoke')
    sections = []

    # Process 'rules' injection
    if injection_config.get('rules'):
        rule_names = injection_config['rules']
        all_rules = get_all_rules()
        rules_by_name = {r.get('name', ''): r for r in all_rules}

        matched_rules = []
        for name in rule_names:
            if name in rules_by_name:
                matched_rules.append(rules_by_name[name])
            else:
                logger.debug(f"context_injection: rule '{name}' not found")

        if matched_rules:
            sections.append('## Injected Rules')
            for rule in matched_rules:
                rule_text = rule.get('rule_text', rule.get('description', ''))
                sections.append(f"### {rule.get('name', 'unknown')}")
                if rule_text:
                    # Truncate long rules
                    sections.append(rule_text[:500] + '...' if len(rule_text) > 500 else rule_text)

    # Process 'decisions' injection
    if injection_config.get('decisions'):
        decision_ids = injection_config['decisions']
        decisions_dir = Path('knowledge/decisions')

        matched_decisions = []
        for decision_id in decision_ids:
            # Try both formats: NNN and NNN-name.yaml
            patterns = [
                decisions_dir / f"{decision_id}.yaml",
                decisions_dir / f"{decision_id}-*.yaml",
            ]
            for pattern in patterns:
                if pattern.name.endswith('*.yaml'):
                    # Glob pattern
                    matches = list(decisions_dir.glob(f"{decision_id}-*.yaml"))
                    if matches:
                        try:
                            import yaml
                            content = matches[0].read_text()
                            decision = yaml.safe_load(content)
                            matched_decisions.append(decision)
                            break
                        except Exception as e:
                            logger.debug(f"context_injection: failed to load decision {matches[0]}: {e}")
                elif pattern.exists():
                    try:
                        import yaml
                        content = pattern.read_text()
                        decision = yaml.safe_load(content)
                        matched_decisions.append(decision)
                        break
                    except Exception as e:
                        logger.debug(f"context_injection: failed to load decision {pattern}: {e}")

        if matched_decisions:
            sections.append('## Injected Decisions')
            for decision in matched_decisions:
                sections.append(f"### Decision {decision.get('id', '?')}: {decision.get('title', 'unknown')}")
                if decision.get('decision'):
                    sections.append(decision['decision'][:500])

    # Process 'files' injection
    if injection_config.get('files'):
        file_patterns = injection_config['files']
        matched_files = []

        for pattern in file_patterns:
            matches = list(Path('.').glob(pattern))
            matched_files.extend(matches[:5])  # Limit per pattern

        if matched_files:
            sections.append('## Injected Files')
            for file_path in matched_files[:10]:  # Total limit
                try:
                    content = file_path.read_text()
                    preview = content[:1000] + '...' if len(content) > 1000 else content
                    sections.append(f"### {file_path}")
                    sections.append(f"```\n{preview}\n```")
                except Exception as e:
                    logger.debug(f"context_injection: failed to read {file_path}: {e}")

    # Process 'auto' injection
    if injection_config.get('auto'):
        try:
            auto_context = gather_context(task, max_results=3)
            auto_formatted = _format_context_for_prompt(auto_context)
            if auto_formatted:
                sections.append('## Auto-detected Context')
                sections.append(auto_formatted.strip())
        except Exception as e:
            logger.debug(f"context_injection: auto context failed: {e}")

    if not sections:
        return ''

    return '\n\n<injected-context>\n' + '\n'.join(sections) + '\n</injected-context>\n\n'


async def invoke_agent(
    agent_name: str,
    task: str,
    run_id: Optional[str] = None,
    verbose: bool = False,
    background: bool = False,
    project: Optional[str] = None,
) -> dict:
    """
    Invoke an SDK-based agent.

    Args:
        agent_name: Name of agent (builder, web-researcher, git-reviewer)
        task: The task description/prompt
        run_id: Optional run ID to link this invocation
        verbose: Print output as it streams
        background: If True, spawn agent in background subprocess and return immediately
        project: Optional project name for progress tracking (auto-detected if not provided)

    Returns:
        dict with:
            - agent: Agent name
            - success: Whether invocation succeeded (always True for background mode)
            - output: Agent's text output (empty for background mode)
            - tool_uses: List of tools the agent used (empty for background mode)
            - duration_ms: How long it took (0 for background mode)
            - run_id: Run ID (always provided, especially important for background mode)
            - depth: Current recursion depth
            - error: Error message if failed
            - background: True if running in background mode
    """
    # Check recursion depth limit
    current_depth = int(os.environ.get("PILOT_AGENT_DEPTH", "0"))
    if current_depth >= MAX_AGENT_DEPTH:
        return {
            "agent": agent_name,
            "success": False,
            "error": f"Max agent depth ({MAX_AGENT_DEPTH}) exceeded - cannot spawn more agents",
            "output": "",
            "duration_ms": 0,
            "depth": current_depth,
        }

    # Handle background mode - spawn subprocess and return immediately
    if background:
        import uuid
        import subprocess

        # Generate run_id if not provided
        if run_id is None:
            run_id = f"run_{uuid.uuid4().hex[:12]}"

        # Detect project for progress tracking (simple pattern matching)
        bg_project = project or _extract_project_from_task(task)

        # Create initial progress file BEFORE spawning so caller can poll immediately
        if bg_project:
            initial_progress = ProgressFile(
                run_id=run_id,
                agent=agent_name,
                project=bg_project,
                started_at=datetime.now(),
                status=ProgressStatus.PENDING,
                last_heartbeat=datetime.now(),
                phase='Starting background process',
                messages_processed=0,
            )
            write_progress(bg_project, initial_progress)

        # Spawn subprocess - use Popen for true detachment
        cmd = [
            "uv", "run", "python", "-m", "lib.invoke",
            agent_name, task,
            "--run-id", run_id,
        ]
        if verbose:
            cmd.append("--verbose")

        # Start detached process
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # Detach from parent
        )

        # Return immediately with run_id
        return {
            "agent": agent_name,
            "success": True,
            "output": "",
            "tool_uses": [],
            "duration_ms": 0,
            "run_id": run_id,
            "depth": current_depth,
            "background": True,
            "project": bg_project,
        }

    # Pre-invocation guard: check for dangerous commands and misrouted tasks
    legitimacy_check = check_task_legitimacy(task, agent_name)
    if legitimacy_check.get("error"):
        return {
            "agent": agent_name,
            "success": False,
            "error": legitimacy_check.get("message", "Task blocked by safety guard"),
            "output": "",
            "duration_ms": 0,
            "depth": current_depth,
            "blocked_pattern": legitimacy_check.get("pattern"),
        }
    if legitimacy_check.get("warning"):
        logging.getLogger("pilot.invoke").warning(
            f"Possible misrouted task: {legitimacy_check.get('message')}"
        )

    start_time = datetime.now()

    # Load agent configuration
    config = load_agent_config(agent_name)
    if not config:
        return {
            "agent": agent_name,
            "success": False,
            "error": f"Agent not found: {agent_name}",
            "output": "",
            "duration_ms": 0,
        }

    # Process pre_task hooks (may abort execution)
    try:
        _process_pre_task_hooks(config, task)
    except PreTaskHookError as e:
        return {
            "agent": agent_name,
            "success": False,
            "error": str(e),
            "output": "",
            "duration_ms": int((datetime.now() - start_time).total_seconds() * 1000),
            "depth": current_depth,
        }

    # Build context for agent (with auto-detected project if available)
    detected_project = _extract_project_from_task(task)
    context = build_context(agent_name, project_id=detected_project)
    if detected_project:
        logging.getLogger("pilot.invoke").info(
            f"[AUTO] Injected project context for '{detected_project}'"
        )

    # Initialize progress tracking (only if we have a project)
    # Generate run_id if not provided
    if run_id is None:
        import uuid
        run_id = f"run_{uuid.uuid4().hex[:12]}"

    progress_project = project or detected_project  # Track which project to use for progress
    if progress_project:
        initial_progress = ProgressFile(
            run_id=run_id,
            agent=agent_name,
            project=progress_project,
            started_at=start_time,
            status=ProgressStatus.RUNNING,
            last_heartbeat=start_time,
            phase='Initializing agent',
            messages_processed=0,
        )
        write_progress(progress_project, initial_progress)

    # Determine model - default to opus for better reasoning
    model_key = config.get("model", "opus")
    model = MODEL_MAP.get(model_key, MODEL_MAP["opus"])

    # Get allowed tools from agent config (if specified)
    allowed_tools = config.get("tools", [])

    # Handle thinking configuration via settings file
    settings_file = None
    cleanup_settings = False
    if config.get('thinking'):
        # Create a temporary settings file with thinking configuration
        import tempfile
        import json

        settings_data = {
            'thinking': {
                'enabled': config['thinking'].get('type') == 'enabled',
                'budget_tokens': config['thinking'].get('budget_tokens', 10000)
            }
        }

        # Create temp file that will be cleaned up after agent runs
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.json',
            delete=False,
            prefix='agent_settings_'
        ) as f:
            json.dump(settings_data, f)
            settings_file = f.name
            cleanup_settings = True
            logger.debug(f"Created thinking settings file: {settings_file}")

    # Create SDK options
    options = ClaudeCodeOptions(
        system_prompt=context,
        model=model,
        cwd=str(Path.cwd()),
        allowed_tools=allowed_tools if allowed_tools else None,
        settings=settings_file if settings_file else None,
    )

    # Set run ID in environment for tools to pick up
    if run_id:
        os.environ["PILOT_RUN_ID"] = run_id

    # Set incremented depth for child agents
    os.environ["PILOT_AGENT_DEPTH"] = str(current_depth + 1)

    # MANDATORY: Auto-inject repository search context
    # This is CODE ENFORCEMENT - search always happens before agent execution
    repo_context = ''
    try:
        repo_context = repo_search_context(task)
        if repo_context:
            logging.getLogger('pilot.invoke').info(
                f"[ENFORCED] Auto-injected search context for agent '{agent_name}'"
            )
    except Exception as e:
        logging.getLogger('pilot.invoke').warning(f'repo_search context failed: {e}')
        repo_context = ''

    # Additional context from agent-specific injection config (optional)
    extra_context = ''
    if config.get('context_injection'):
        try:
            extra_context = _process_context_injection(config, task)
        except Exception as e:
            logging.getLogger('pilot.invoke').debug(f'Context injection failed: {e}')
            extra_context = ''

    # Combine: repo search context (mandatory) + agent-specific context (optional)
    context_summary = ''
    if repo_context:
        context_summary = f'\n<auto-search-context>\n{repo_context}\n</auto-search-context>\n\n'
    if extra_context:
        context_summary += extra_context

    # Prepare enhanced task with gathered context
    enhanced_task = context_summary + task if context_summary else task

    # Execute query with retry logic for rate limits
    output_text = ""
    tool_uses = []
    attempt = 0
    success = False
    error = None

    messages_processed = 0  # Track messages for progress updates

    while True:
        try:
            # Reset for retry
            output_text = ""
            tool_uses = []
            messages_processed = 0

            async for message in query(prompt=enhanced_task, options=options):
                if isinstance(message, AssistantMessage):
                    messages_processed += 1
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            if verbose:
                                print(block.text, end="", flush=True)
                            output_text += block.text
                        elif isinstance(block, ToolUseBlock):
                            tool_uses.append({
                                "tool": block.name,
                                "input": block.input if hasattr(block, 'input') else None,
                            })
                            # Update progress when tool is used (shows activity)
                            if progress_project:
                                update_heartbeat(
                                    progress_project,
                                    run_id,
                                    phase=f'Using tool: {block.name}',
                                    messages=messages_processed
                                )

                    # Update heartbeat periodically (every 5 messages)
                    if progress_project and messages_processed % 5 == 0:
                        update_heartbeat(
                            progress_project,
                            run_id,
                            phase='Processing messages',
                            messages=messages_processed
                        )

            success = True
            error = None
            break  # Success - exit retry loop

        except Exception as e:
            if is_rate_limit_error(e):
                # Rate limit - retry with backoff (never fail due to rate limits)
                attempt += 1
                retry_after = extract_retry_after(e)
                backoff = calculate_backoff(attempt - 1, retry_after)  # attempt-1 for 0-indexed backoff calc

                # Calculate total wait time so far for logging
                elapsed = (datetime.now() - start_time).total_seconds()

                # Determine backoff source for logging
                source = f"Retry-After: {retry_after}s" if retry_after else "exponential backoff"

                # Log the retry attempt (always log, not just verbose)
                log_msg = (
                    f"[Rate limited] Attempt {attempt}/{MAX_RETRY_ATTEMPTS}+ | "
                    f"Waiting {backoff:.1f}s ({source}) | "
                    f"Total elapsed: {elapsed:.1f}s"
                )

                if verbose:
                    print(f"\n{log_msg}", flush=True)

                # Also log to agent log for debugging
                logging.getLogger("pilot.invoke").warning(
                    f"Rate limit hit for agent '{agent_name}': {log_msg}"
                )

                await asyncio.sleep(backoff)
                # Continue loop - never fail due to rate limits
            else:
                # Non-rate-limit error - fail immediately
                success = False
                error = f"{type(e).__name__}: {str(e)}"
                break

    # Calculate duration
    end_time = datetime.now()
    duration_ms = int((end_time - start_time).total_seconds() * 1000)

    result = {
        "agent": agent_name,
        "success": success,
        "output": output_text,
        "tool_uses": tool_uses,
        "duration_ms": duration_ms,
        "run_id": run_id,
        "depth": current_depth,
        "retry_attempts": attempt,
    }

    if error:
        result["error"] = error

    # Update progress with completion/failure status
    if progress_project:
        if success:
            # Extract files created from tool uses for artifacts_created
            artifacts = []
            for tool_use in tool_uses:
                if tool_use.get("tool") == "Write" and tool_use.get("input"):
                    file_path = tool_use["input"].get("file_path")
                    if file_path:
                        artifacts.append(file_path)
            # Create summary from first 200 chars of output
            summary = output_text[:200].strip() if output_text else "Completed successfully"
            if len(output_text) > 200:
                summary += "..."
            mark_completed(progress_project, run_id, summary, artifacts or None)
        else:
            mark_failed(progress_project, run_id, error or "Unknown error")

    # Process post_task hooks (fire-and-forget)
    await _process_post_task_hooks(
        config=config,
        tool_uses=tool_uses,
        task=task,
        success=success,
        run_id=run_id,
        verbose=verbose,
    )

    # Clean up temporary settings file if created
    if cleanup_settings and settings_file:
        try:
            os.unlink(settings_file)
            logger.debug(f"Cleaned up settings file: {settings_file}")
        except Exception as e:
            logger.warning(f"Failed to clean up settings file {settings_file}: {e}")

    # Log the invocation
    log_agent(
        agent=agent_name,
        input={"task": task, "run_id": run_id},
        output=result,
    )

    # Create run manifest for project context (delegation tracking)
    if success:
        _create_delegation_manifest(agent_name, task, run_id)

        # Track file attributions for audit trail
        try:
            from lib.attribution import track_agent_files
            tracked_count = track_agent_files(agent_name, tool_uses, run_id)
            if tracked_count > 0:
                logger.debug(f"Tracked {tracked_count} file modifications for {agent_name}")
        except Exception as e:
            # Log but don't fail - attribution is audit feature
            logger.warning(f"Failed to track file attributions: {e}")

        # Track git-reviewer APPROVED verdicts for lib.approve verification
        # This ensures lib.approve can only succeed if git-reviewer was actually invoked
        if agent_name == "git-reviewer" and "APPROVED" in output_text:
            try:
                from lib.approve import record_reviewer_session
                # Get current staged diff hash
                diff_result = subprocess.run(
                    ["git", "diff", "--cached"],
                    capture_output=True,
                )
                diff_hash = hashlib.sha256(diff_result.stdout).hexdigest()
                record_reviewer_session(diff_hash)
                logger.info(f"Recorded git-reviewer APPROVED session with diff hash {diff_hash[:16]}...")
            except Exception as e:
                logger.warning(f"Failed to record reviewer session: {e}")

    return result


def invoke_sync(agent_name: str, task: str, **kwargs) -> dict:
    """Synchronous wrapper for invoke_agent."""
    return asyncio.run(invoke_agent(agent_name, task, **kwargs))


def main():
    """CLI entry point for agent invocation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Invoke SDK-based agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Invoke builder agent
    uv run python -m lib.invoke builder "Create a hello world tool"

    # Invoke with JSON input
    uv run python -m lib.invoke builder '{"task": "Fix the bug"}'

    # With run ID for tracking
    uv run python -m lib.invoke builder "Task" --run-id 20250126_143022_abc

    # List available agents
    uv run python -m lib.invoke --list
""",
    )

    parser.add_argument("agent", nargs="?", help="Agent name (builder, web-researcher, git-reviewer)")
    parser.add_argument("task", nargs="?", help="Task description or JSON object")
    parser.add_argument("--run-id", help="Run ID to link this invocation")
    parser.add_argument("--verbose", "-v", action="store_true", help="Stream output")
    parser.add_argument("--list", "-l", action="store_true", help="List available agents")

    args = parser.parse_args()

    if args.list:
        agents_dir = Path("agents")
        if agents_dir.exists():
            print("Available agents:")
            for f in agents_dir.glob("*.yaml"):
                config = load_agent_config(f.stem)
                desc = config.get("description", "") if config else ""
                print(f"  {f.stem}: {desc}")
        else:
            print("No agents directory found")
        return

    if not args.agent:
        parser.print_help()
        sys.exit(1)

    if not args.task:
        print("Error: task required", file=sys.stderr)
        sys.exit(1)

    # Parse task - could be plain string or JSON
    task = args.task
    if task.startswith("{"):
        try:
            task_data = json.loads(task)
            task = task_data.get("task", task)
        except json.JSONDecodeError:
            pass  # Use as-is

    # Run invocation
    result = invoke_sync(
        args.agent,
        task,
        run_id=args.run_id,
        verbose=args.verbose,
    )

    # Output result as JSON
    if not args.verbose:
        print(json.dumps(result, indent=2, default=str))
    else:
        print("\n---")
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
