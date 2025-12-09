"""
Incremental index utilities for the pilot system.

Provides functions to update the unified index without full rebuilds.
This module enables adding new items to data/index.json without
regenerating the entire index.

Usage:
    from lib.indexer import incremental_index, get_index_status

    # Add a new item to the index
    result = incremental_index('data/deep_research/results/xxx/metadata.yaml')

    # Check result
    if result['success']:
        print(f"Indexed {result['type']}: {result['path']}")
    else:
        print(f"Error: {result.get('error')}")

    # Get index statistics
    status = get_index_status()
    print(f"Index has {status['count']} items")

CLI Usage:
    python -m lib.indexer <path>     # Index a single file
    python -m lib.indexer rebuild    # Rebuild deep_research entries
    python -m lib.indexer status     # Show index statistics
"""

from pathlib import Path
import json
import os
import tempfile
from datetime import datetime

import yaml

from .embed import embed
from .index import index_yaml, derive_type, should_index

INDEX_PATH = Path('data/index.json')
DEEP_RESEARCH_RESULTS_DIR = Path('data/deep_research/results')


def update_index(item: dict) -> dict:
    """
    Atomically update the index with a new or updated item.

    This function:
    1. Loads existing index.json
    2. Removes any existing entry with the same path
    3. Appends the new item to items array
    4. Updates count and generated_at metadata
    5. Writes atomically using temp file + rename

    Args:
        item: Index item dict with at minimum a 'path' field

    Returns:
        dict with keys:
            - success: bool - whether the update succeeded
            - updated_count: int - number of items added (always 1 on success)
            - removed_count: int - number of existing items removed (0 or 1)
            - path: str - the item's path
            - error: str - error message (if failed)
    """
    # Validate item has required 'path' field
    if 'path' not in item:
        return {
            'success': False,
            'error': 'Item must have a "path" field',
            'updated_count': 0,
            'removed_count': 0,
            'path': None
        }

    item_path = item['path']

    try:
        # Load existing index
        if INDEX_PATH.exists():
            with open(INDEX_PATH) as f:
                index_data = json.load(f)
        else:
            index_data = {'generated_at': '', 'count': 0, 'items': []}

        # Remove existing item with same path
        original_count = len(index_data['items'])
        index_data['items'] = [i for i in index_data['items'] if i.get('path') != item_path]
        removed_count = original_count - len(index_data['items'])

        # Append new item
        index_data['items'].append(item)

        # Update metadata
        index_data['count'] = len(index_data['items'])
        index_data['generated_at'] = datetime.now().isoformat()

        # Ensure parent directory exists
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: temp file + rename
        with tempfile.NamedTemporaryFile(
            mode='w',
            dir=INDEX_PATH.parent,
            delete=False,
            suffix='.json'
        ) as f:
            json.dump(index_data, f, indent=2, default=str)
            temp_path = f.name

        os.rename(temp_path, INDEX_PATH)

        return {
            'success': True,
            'updated_count': 1,
            'removed_count': removed_count,
            'path': item_path
        }

    except json.JSONDecodeError as e:
        return {
            'success': False,
            'error': f'Invalid JSON in index file: {e}',
            'updated_count': 0,
            'removed_count': 0,
            'path': item_path
        }
    except OSError as e:
        # Clean up temp file if it exists
        if 'temp_path' in locals():
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        return {
            'success': False,
            'error': f'File operation failed: {e}',
            'updated_count': 0,
            'removed_count': 0,
            'path': item_path
        }


def create_deep_research_index_item(result_dir: Path) -> dict | None:
    """
    Create an index item for a deep_research result directory.

    Reads metadata.yaml from the directory and creates a searchable index item
    that includes query and output summary for semantic search.

    Args:
        result_dir: Path to deep_research result directory
                   (e.g., 'data/deep_research/results/xxx/')

    Returns:
        Index item dict matching index_yaml format, or None if metadata.yaml missing
    """
    metadata_path = result_dir / 'metadata.yaml'

    # Return None if metadata.yaml doesn't exist
    if not metadata_path.exists():
        return None

    # Read metadata
    try:
        metadata = yaml.safe_load(metadata_path.read_text()) or {}
    except yaml.YAMLError:
        return None

    # Extract key fields
    query = metadata.get('query', '')
    run_id = metadata.get('run_id', result_dir.name)

    # Build searchable text from query + output summary
    searchable_parts = []

    if query:
        searchable_parts.append(query)

    # Try to read output.yaml for additional context
    output_path = result_dir / 'output.yaml'
    if output_path.exists():
        try:
            output_text = output_path.read_text()
            # Take first 2000 chars of output for searchable text
            searchable_parts.append(output_text[:2000])
        except Exception:
            pass

    # Combine searchable text
    searchable_text = '\n'.join(searchable_parts) if searchable_parts else run_id

    # Use query as description, fallback to run_id
    description = query if query else run_id

    # Generate embedding (truncate to 2000 chars for embedding)
    embedding = embed(searchable_text[:2000]) if searchable_text else []

    # Derive tags
    tags = ['research', 'deep_research']
    if metadata.get('processor'):
        tags.append(metadata['processor'])

    return {
        'path': str(metadata_path),
        'type': 'deep_research',
        'name': run_id,
        'description': description[:500],  # Truncate description
        'content': metadata,
        'text': searchable_text[:5000],  # Truncate for storage
        'embedding': embedding,
        'tags': list(set(tags)),
    }


def rebuild_deep_research_index() -> dict:
    """
    Rebuild the deep_research portion of the index.

    Scans data/deep_research/results/ directory and creates index items
    for each result, replacing any stale deep_research items in the index.

    Returns:
        dict with keys:
            - success: bool
            - items_added: int - number of deep_research items added
            - items_removed: int - number of stale items removed
            - total_count: int - total items in index after rebuild
            - error: str (if failed)
    """
    try:
        # 1. Check if results directory exists
        if not DEEP_RESEARCH_RESULTS_DIR.exists():
            return {
                'success': True,
                'items_added': 0,
                'items_removed': 0,
                'total_count': 0,
                'note': 'No deep_research results directory found'
            }

        # 2. Create index items for all results
        new_items = []
        for result_dir in DEEP_RESEARCH_RESULTS_DIR.iterdir():
            if result_dir.is_dir() and (result_dir / 'metadata.yaml').exists():
                item = create_deep_research_index_item(result_dir)
                if item:
                    new_items.append(item)

        # 3. Load existing index
        if INDEX_PATH.exists():
            with open(INDEX_PATH) as f:
                index_data = json.load(f)
        else:
            index_data = {'generated_at': '', 'count': 0, 'items': []}

        # 4. Remove ALL existing deep_research items (handles stale items)
        original_count = len(index_data['items'])
        index_data['items'] = [i for i in index_data['items'] if i.get('type') != 'deep_research']
        removed_count = original_count - len(index_data['items'])

        # 5. Add all new deep_research items
        index_data['items'].extend(new_items)

        # 6. Update metadata
        index_data['count'] = len(index_data['items'])
        index_data['generated_at'] = datetime.now().isoformat()

        # 7. Atomic write
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode='w',
            dir=INDEX_PATH.parent,
            delete=False,
            suffix='.json'
        ) as f:
            json.dump(index_data, f, indent=2, default=str)
            temp_path = f.name

        os.rename(temp_path, INDEX_PATH)

        return {
            'success': True,
            'items_added': len(new_items),
            'items_removed': removed_count,
            'total_count': index_data['count']
        }

    except Exception as e:
        # Clean up temp file if it exists
        if 'temp_path' in locals():
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        return {
            'success': False,
            'error': str(e),
            'items_added': 0,
            'items_removed': 0,
            'total_count': 0
        }


def incremental_index(path: str | Path) -> dict:
    """
    Add or update a single item in the index.

    This is the entry point for incremental indexing. It validates the path,
    derives the item type, creates the index item, and writes it atomically
    to data/index.json.

    Args:
        path: Path to the file to index (e.g., 'data/deep_research/results/xxx/metadata.yaml')

    Returns:
        dict with keys:
            - success: bool - whether the operation succeeded
            - item_count: int - number of items indexed (0 or 1)
            - type: str - derived type of the item (if successful)
            - path: str - normalized path string
            - item: dict - the created index item (if successful)
            - index_update: dict - result from update_index() with updated_count, removed_count
            - error: str - error message (if failed)
    """
    path = Path(path)

    # Validate path exists
    if not path.exists():
        return {
            'success': False,
            'error': f'Path does not exist: {path}',
            'item_count': 0,
            'path': str(path)
        }

    # Check if path should be indexed (not in skip patterns)
    if not should_index(path):
        return {
            'success': False,
            'error': f'Path excluded by skip patterns: {path}',
            'item_count': 0,
            'path': str(path)
        }

    # Derive the item type from path
    item_type = derive_type(path)

    # Handle deep_research type - check if path is metadata.yaml in a result dir
    if item_type == 'deep_research' and path.name == 'metadata.yaml':
        result_dir = path.parent
        item = create_deep_research_index_item(result_dir)

        if item is None:
            return {
                'success': False,
                'error': f'Failed to create index item for deep_research: {path}',
                'item_count': 0,
                'path': str(path)
            }

        # Write item to index atomically
        update_result = update_index(item)

        if not update_result['success']:
            return {
                'success': False,
                'error': update_result.get('error', 'Failed to update index'),
                'item_count': 0,
                'path': str(path),
                'item': item
            }

        return {
            'success': True,
            'item_count': 1,
            'type': item_type,
            'path': str(path),
            'item': item,
            'index_update': update_result
        }

    # For other YAML types, use the generic index_yaml function
    item = index_yaml(path)

    if item is None:
        return {
            'success': False,
            'error': f'Failed to create index item for {item_type}: {path}',
            'item_count': 0,
            'path': str(path)
        }

    # Write item to index atomically
    update_result = update_index(item)

    if not update_result['success']:
        return {
            'success': False,
            'error': update_result.get('error', 'Failed to update index'),
            'item_count': 0,
            'path': str(path),
            'item': item
        }

    return {
        'success': True,
        'item_count': 1,
        'type': item_type,
        'path': str(path),
        'item': item,
        'index_update': update_result
    }


def get_index_status() -> dict:
    """
    Get index statistics.

    Returns:
        dict with keys:
            - success: bool
            - exists: bool - whether index file exists
            - count: int - total items in index
            - by_type: dict - count of items by type
            - generated_at: str - ISO timestamp of last generation
    """
    try:
        if not INDEX_PATH.exists():
            return {
                'success': True,
                'exists': False,
                'count': 0,
                'by_type': {},
                'generated_at': None
            }

        with open(INDEX_PATH) as f:
            index_data = json.load(f)

        # Count by type
        by_type = {}
        for item in index_data.get('items', []):
            item_type = item.get('type', 'unknown')
            by_type[item_type] = by_type.get(item_type, 0) + 1

        return {
            'success': True,
            'exists': True,
            'count': index_data.get('count', 0),
            'by_type': by_type,
            'generated_at': index_data.get('generated_at')
        }
    except json.JSONDecodeError as e:
        return {
            'success': False,
            'error': f'Invalid JSON in index file: {e}',
            'exists': True,
            'count': 0,
            'by_type': {},
            'generated_at': None
        }
    except OSError as e:
        return {
            'success': False,
            'error': f'Failed to read index file: {e}',
            'exists': False,
            'count': 0,
            'by_type': {},
            'generated_at': None
        }


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print('Usage: python -m lib.indexer <command>')
        print('')
        print('Commands:')
        print('  <path>   - Incrementally index a file into data/index.json')
        print('  rebuild  - Rebuild all deep_research index entries')
        print('  status   - Show index statistics')
        print('')
        print('Examples:')
        print('  python -m lib.indexer data/deep_research/results/xxx/metadata.yaml')
        print('  python -m lib.indexer rebuild')
        print('  python -m lib.indexer status')
        sys.exit(0)

    command = sys.argv[1]

    if command == 'rebuild':
        result = rebuild_deep_research_index()
        print(json.dumps(result, indent=2))
    elif command == 'status':
        result = get_index_status()
        print(json.dumps(result, indent=2))
    else:
        # Assume it's a path to index
        result = incremental_index(command)
        print(json.dumps(result, indent=2))
