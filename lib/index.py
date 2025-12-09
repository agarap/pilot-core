"""Universal index builder for the pilot system - optimized for DuckDB querying."""

import json
import re
from datetime import datetime
from pathlib import Path

import yaml

from .embed import embed


# Path-based type derivation - order matters (more specific patterns first)
TYPE_PATTERNS = [
    ('agents/', 'agent'),
    ('system/rules/', 'rule'),
    ('system/', 'config'),
    ('tools/', 'tool'),
    ('lib/', 'lib'),
    ('knowledge/decisions/', 'decision'),
    ('knowledge/facts/', 'fact'),
    ('knowledge/lessons/', 'lesson'),
    ('.runs/', 'run'),
    ('data/parallel_tasks/results/', 'parallel_task'),
    ('data/parallel_findall/results/', 'parallel_findall'),
    ('data/deep_research/results/', 'deep_research'),
    ('projects/', 'project'),
]

# Directories to skip
SKIP_PATTERNS = ['.git', '.dev', 'node_modules', '__pycache__',
                 '.pytest_cache', 'logs/', 'workspaces/', 'output/']


def derive_type(path: Path) -> str:
    """Derive item type from path using prefix matching."""
    path_str = str(path)
    for pattern, type_name in TYPE_PATTERNS:
        # Match only at start of path or after a path separator
        # This prevents 'agents/' from matching 'self-improving-agents/'
        if path_str.startswith(pattern) or f'/{pattern}' in path_str:
            return type_name
    return 'file'


def should_index(path: Path) -> bool:
    """Skip non-content directories."""
    path_str = str(path)
    return not any(p in path_str for p in SKIP_PATTERNS)


def flatten_to_text(obj, max_depth=5) -> str:
    """Recursively extract all string values from nested dict/list."""
    if max_depth <= 0:
        return ''
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return ' '.join(flatten_to_text(v, max_depth - 1) for v in obj.values())
    if isinstance(obj, list):
        return ' '.join(flatten_to_text(item, max_depth - 1) for item in obj)
    return str(obj) if obj is not None else ''


def extract_description(content: dict) -> str:
    """Try common description fields."""
    for key in ['description', 'desc', 'summary', 'abstract', 'query', 'task', 'objective']:
        if key in content and isinstance(content[key], str):
            return content[key][:500]
    return ''


def extract_tags(content: dict, path: Path) -> list:
    """Extract tags from content and derive from path."""
    tags = content.get('tags', []) if isinstance(content, dict) else []
    if not isinstance(tags, list):
        tags = [tags] if tags else []
    # Add path-derived tags
    path_str = str(path)
    if 'parallel' in path_str or 'research' in path_str:
        tags.append('research')

    # Add knowledge-specific tags for filtering
    item_type = derive_type(path)
    if item_type in ('lesson', 'decision', 'fact'):
        # Add category as a tag for knowledge entries
        category = content.get('category')
        if category:
            tags.append(category)
        # Add severity as a tag if high or medium (for prioritized filtering)
        severity = content.get('severity')
        if severity in ('high', 'medium'):
            tags.append(f'severity-{severity}')

    return list(set(tags))


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown."""
    if text.startswith('---'):
        match = re.match(r'^---\n(.*?)\n---\n?(.*)', text, re.DOTALL)
        if match:
            try:
                frontmatter = yaml.safe_load(match.group(1)) or {}
                return frontmatter, match.group(2).strip()
            except yaml.YAMLError:
                pass
    return {}, text


def index_yaml(path: Path) -> dict:
    """Universal YAML indexer - stores full content for DuckDB JSON querying."""
    content = yaml.safe_load(path.read_text()) or {}
    text = flatten_to_text(content)
    item_type = derive_type(path)

    record = {
        'path': str(path),
        'type': item_type,
        'name': content.get('name') or content.get('title') or path.stem,
        'description': extract_description(content),
        'content': content,  # Full YAML as dict - DuckDB queries it
        'text': text,  # Full text for comprehensive search (no truncation)
        'embedding': embed(text[:8000]) if text else [],  # Increased embedding context
        'tags': extract_tags(content, path),
    }

    # Add knowledge-specific top-level fields for easy filtering
    if item_type in ('lesson', 'decision', 'fact'):
        # category: architecture, code-quality, process, etc.
        if 'category' in content:
            record['category'] = content['category']
        # severity: high, medium, low (lessons)
        if 'severity' in content:
            record['severity'] = content['severity']
        # status: proposed, accepted, superseded (decisions)
        if 'status' in content:
            record['status'] = content['status']

    return record


def index_md(path: Path) -> dict:
    """Universal MD indexer - parses frontmatter + full body for comprehensive search."""
    text = path.read_text()
    frontmatter, body = parse_frontmatter(text)

    # Store full body for comprehensive search (no truncation)
    # For very large files, we still limit embedding input
    return {
        'path': str(path),
        'type': derive_type(path),
        'name': frontmatter.get('name') or frontmatter.get('title') or path.stem,
        'description': frontmatter.get('description', ''),
        'content': {'frontmatter': frontmatter, 'body': body},  # Full body, no truncation
        'text': body,  # Full text for search
        'embedding': embed(body[:8000]) if body else [],  # Increased embedding context
        'tags': extract_tags(frontmatter, path),
    }


def parse_python_file(path: Path) -> dict:
    """Parse Python file for docstring metadata."""
    source = path.read_text()

    metadata = {
        'path': str(path),
        'name': path.stem,
        'type': derive_type(path),
        'description': '',
        'tags': [],
        'content': {'parameters': {}, 'returns': ''},
        'text': '',
        'embedding': [],
    }

    # Try to parse YAML docstring header for tools
    if source.startswith('"""'):
        end = source.find('"""', 3)
        if end > 0:
            docstring = source[3:end]
            try:
                doc_data = yaml.safe_load(docstring)
                if isinstance(doc_data, dict):
                    metadata['name'] = doc_data.get('tool', path.stem)
                    metadata['description'] = doc_data.get('description', '')
                    metadata['tags'] = doc_data.get('tags', [])
                    metadata['content'] = {
                        'parameters': doc_data.get('parameters', {}),
                        'returns': doc_data.get('returns', ''),
                    }
                    metadata['text'] = docstring[:2000]
                    metadata['embedding'] = embed(docstring[:2000])
            except yaml.YAMLError:
                # Plain text docstring
                desc = docstring.strip().split('\n')[0]
                metadata['description'] = desc
                metadata['text'] = desc
                metadata['embedding'] = embed(desc) if desc else []

    return metadata


def index_all() -> dict:
    """
    Universal index of all YAML and MD files.

    Indexes:
    - All *.yaml files (full content as JSON)
    - All *.md files (frontmatter + body)
    - tools/*.py (docstring metadata)
    - lib/*.py (docstring metadata)

    Type is derived from path, not from file content.
    Full content stored for DuckDB JSON querying.
    """
    index = []
    base = Path('.')

    # Index ALL yaml files
    for path in base.rglob('*.yaml'):
        if should_index(path):
            try:
                record = index_yaml(path)
                index.append(record)
            except Exception:
                pass  # Skip files that fail to parse

    # Index ALL md files
    for path in base.rglob('*.md'):
        if should_index(path):
            try:
                record = index_md(path)
                index.append(record)
            except Exception:
                pass

    # Index Python tools and lib
    for subdir in ['tools', 'lib']:
        dir_path = base / subdir
        if dir_path.exists():
            for path in dir_path.glob('*.py'):
                if path.name.startswith('_'):
                    continue
                try:
                    record = parse_python_file(path)
                    index.append(record)
                except Exception:
                    pass

    # Write index
    data_dir = base / 'data'
    data_dir.mkdir(exist_ok=True)

    output = {
        'generated_at': datetime.now().isoformat(),
        'count': len(index),
        'items': index
    }

    with open(data_dir / 'index.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f'Indexed {len(index)} items to data/index.json')
    return output


if __name__ == '__main__':
    index_all()
