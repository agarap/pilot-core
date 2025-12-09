"""
tool: web_fetch
description: Extract content from specific URLs using Parallel API
parameters:
  urls: List of URLs to extract content from
  objective: Optional objective to focus extraction on relevant content
  excerpts: Whether to return relevant excerpts (default True)
  full_content: Whether to return full page content (default False)
returns: Extracted content with title, excerpts, and optionally full content
"""

import os
import httpx
from typing import Optional


PARALLEL_API_URL = "https://api.parallel.ai/v1beta/extract"
PARALLEL_BETA_HEADER = "search-extract-2025-10-10"


def web_fetch(
    urls: list[str],
    objective: Optional[str] = None,
    excerpts: bool = True,
    full_content: bool = False,
) -> dict:
    """
    Extract content from URLs using Parallel API.

    Args:
        urls: List of URLs to extract content from
        objective: Optional objective to focus extraction
        excerpts: Whether to return relevant excerpts (default True)
        full_content: Whether to return full content (default False)

    Returns:
        dict with extract_id, results list, and errors list
    """
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.environ.get("PARALLEL_API_KEY")
    if not api_key:
        return {"error": "PARALLEL_API_KEY not set in environment"}

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "parallel-beta": PARALLEL_BETA_HEADER,
    }

    payload = {
        "urls": urls,
        "excerpts": excerpts,
        "full_content": full_content,
    }

    if objective:
        payload["objective"] = objective

    try:
        with httpx.Client(timeout=300.0) as client:  # 5 minutes
            response = client.post(PARALLEL_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        return {
            "error": f"HTTP {e.response.status_code}: {e.response.text}",
        }
    except httpx.RequestError as e:
        return {"error": f"Request failed: {str(e)}"}


if __name__ == "__main__":
    # Test the tool
    import json
    from dotenv import load_dotenv

    load_dotenv()

    result = web_fetch(
        urls=["https://www.anthropic.com"],
        objective="What does Anthropic do?",
    )
    print(json.dumps(result, indent=2))
