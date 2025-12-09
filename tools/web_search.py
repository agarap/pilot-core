"""
tool: web_search
description: Search the web using Parallel API and return relevant results with excerpts
parameters:
  objective: Natural language description of what to search for
  search_queries: Optional list of keyword search queries
  max_results: Maximum number of results to return (default 10)
returns: List of search results with url, title, publish_date, and excerpts
"""

import os
import httpx
from typing import Optional


PARALLEL_API_URL = "https://api.parallel.ai/v1beta/search"
PARALLEL_BETA_HEADER = "search-extract-2025-10-10"


def web_search(
    objective: str,
    search_queries: Optional[list[str]] = None,
    max_results: int = 10,
) -> dict:
    """
    Search the web using Parallel API.

    Args:
        objective: Natural language description of what to search for
        search_queries: Optional list of keyword search queries
        max_results: Maximum number of results (default 10)

    Returns:
        dict with search_id and results list
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
        "objective": objective,
        "max_results": max_results,
    }

    if search_queries:
        payload["search_queries"] = search_queries

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

    result = web_search("What is the current weather in San Francisco?")
    print(json.dumps(result, indent=2))
