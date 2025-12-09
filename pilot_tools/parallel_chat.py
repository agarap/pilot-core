"""
tool: parallel_chat
description: Fast web-researched chat completions using Parallel.ai Chat API (OpenAI-compatible)
parameters:
  For parallel_chat:
    messages: List of message dicts with 'role' and 'content' keys
    stream: Whether to stream response (not implemented, returns error if True)
    max_tokens: Optional max tokens for response
    temperature: Optional temperature for response
  For parallel_chat_simple:
    query: Simple string query for single-turn chat
  For parallel_chat_json:
    message: The user message/query
    json_schema: JSON Schema dict defining expected response structure
    system_prompt: Optional system prompt
    schema_name: Name for the schema (default: 'response')
returns: Dict with content (response text), usage, model, or error
         For parallel_chat_json: Parsed JSON dict matching schema, or error dict
"""

import json
import os
from typing import Optional

import httpx


PARALLEL_CHAT_URL = "https://api.parallel.ai/chat/completions"
PARALLEL_MODEL = "speed"  # Only supported model


def _get_api_key() -> Optional[str]:
    """Get API key from environment, loading .env if needed."""
    from dotenv import load_dotenv
    load_dotenv()
    return os.environ.get("PARALLEL_API_KEY")


def parallel_chat(
    messages: list[dict],
    stream: bool = False,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> dict:
    """
    Fast web-researched chat completion using Parallel.ai Chat API.

    This is an OpenAI-compatible endpoint that provides low-latency,
    web-researched responses.

    Args:
        messages: List of message dicts with 'role' and 'content' keys.
                  Roles: 'system', 'user', 'assistant'
        stream: Whether to stream response (not implemented, returns error if True)
        max_tokens: Optional max tokens for response
        temperature: Optional temperature for response (0.0 to 2.0)

    Returns:
        dict with 'content' (response text), 'usage', 'model', or 'error'
    """
    if stream:
        return {"error": "Streaming not implemented. Use stream=False."}

    api_key = _get_api_key()
    if not api_key:
        return {"error": "PARALLEL_API_KEY not set in environment"}

    # Validate messages
    if not messages:
        return {"error": "messages is required and must not be empty"}

    for msg in messages:
        if not isinstance(msg, dict):
            return {"error": "Each message must be a dict with 'role' and 'content'"}
        if "role" not in msg or "content" not in msg:
            return {"error": "Each message must have 'role' and 'content' keys"}
        if msg["role"] not in ["system", "user", "assistant"]:
            return {"error": f"Invalid role: {msg['role']}. Must be system, user, or assistant"}

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",  # Note: Bearer, not x-api-key
    }

    payload = {
        "model": PARALLEL_MODEL,
        "messages": messages,
        "stream": False,
    }

    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    if temperature is not None:
        payload["temperature"] = temperature

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(PARALLEL_CHAT_URL, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()

            # Extract the response content for convenience
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
            else:
                content = ""

            return {
                "content": content,
                "model": result.get("model", PARALLEL_MODEL),
                "usage": result.get("usage", {}),
                "id": result.get("id"),
                "raw": result,  # Include raw response for debugging
            }

    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except httpx.RequestError as e:
        return {"error": f"Request failed: {str(e)}"}


def parallel_chat_simple(query: str) -> str:
    """
    Simple single-turn chat for quick queries.

    Args:
        query: The question or query to ask

    Returns:
        Response text string (or error message prefixed with "Error: ")
    """
    result = parallel_chat([{"role": "user", "content": query}])

    if "error" in result:
        return f"Error: {result['error']}"

    return result.get("content", "")


def parallel_chat_with_system(query: str, system_prompt: str) -> dict:
    """
    Chat with a custom system prompt.

    Args:
        query: The user's question
        system_prompt: Instructions for how to respond

    Returns:
        Full result dict with content, usage, model, or error
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]
    return parallel_chat(messages)


def parallel_chat_conversation(messages: list[dict]) -> dict:
    """
    Continue a multi-turn conversation.

    This is an alias for parallel_chat, provided for clarity.

    Args:
        messages: Full conversation history as list of message dicts

    Returns:
        Full result dict with content, usage, model, or error
    """
    return parallel_chat(messages)


def parallel_chat_json(
    message: str,
    json_schema: dict,
    system_prompt: Optional[str] = None,
    schema_name: str = "response",
) -> dict:
    """
    Chat with structured JSON output following a schema.

    Uses the OpenAI-compatible response_format parameter to request
    JSON output that conforms to the provided schema.

    Args:
        message: The user message/query
        json_schema: JSON Schema dict defining expected response structure
        system_prompt: Optional system prompt for context
        schema_name: Name for the schema (default: 'response')

    Returns:
        Parsed JSON dict matching schema, or {'error': ...} on failure
    """
    api_key = _get_api_key()
    if not api_key:
        return {"error": "PARALLEL_API_KEY not set in environment"}

    # Build messages
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": message})

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    payload = {
        "model": PARALLEL_MODEL,
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "schema": json_schema,
            },
        },
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(PARALLEL_CHAT_URL, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()

            # Extract and parse the JSON content
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                if content:
                    try:
                        parsed = json.loads(content)
                        return parsed
                    except json.JSONDecodeError as e:
                        return {"error": f"Failed to parse JSON response: {e}", "raw_content": content}
            return {"error": "No content in response"}

    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except httpx.RequestError as e:
        return {"error": f"Request failed: {str(e)}"}


# Convenience functions for common use cases

def parallel_chat_factual(query: str) -> dict:
    """
    Ask a factual question optimized for accuracy.

    Args:
        query: Factual question to answer

    Returns:
        Full result dict
    """
    system_prompt = (
        "You are a helpful assistant that provides accurate, factual information. "
        "Base your answers on reliable sources and indicate uncertainty when appropriate."
    )
    return parallel_chat_with_system(query, system_prompt)


def parallel_chat_summary(text: str, max_sentences: int = 3) -> str:
    """
    Summarize text in a few sentences.

    Args:
        text: Text to summarize
        max_sentences: Maximum sentences in summary (default 3)

    Returns:
        Summary string (or error message)
    """
    query = f"Summarize the following in {max_sentences} sentences or less:\n\n{text}"
    return parallel_chat_simple(query)


if __name__ == "__main__":
    import json
    from dotenv import load_dotenv

    load_dotenv()

    # Test simple chat
    print("Testing simple chat...")
    answer = parallel_chat_simple("What is the capital of France?")
    print(f"Answer: {answer}\n")

    # Test full API
    print("Testing full API...")
    result = parallel_chat([
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What does Anthropic do?"},
    ])
    print(json.dumps(result, indent=2))
