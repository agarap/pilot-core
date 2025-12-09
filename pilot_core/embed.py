"""
Embedding utilities for vector similarity search.

Provides lightweight local embeddings using a hash-based approach.
Can be upgraded to use API-based embeddings (OpenAI, Anthropic) for better quality.

The hash-based approach:
- Fast, no API calls needed
- Works offline
- Deterministic
- Good enough for basic similarity

To upgrade to API embeddings, modify the embed() function.
"""

import hashlib
import math
import re
from typing import Optional

# Embedding dimension - balance between quality and storage
EMBEDDING_DIM = 256


def tokenize(text: str) -> list[str]:
    """Simple tokenization: lowercase, split on non-alphanumeric."""
    text = text.lower()
    tokens = re.findall(r'\b[a-z0-9]+\b', text)
    return tokens


def hash_token(token: str, dim: int = EMBEDDING_DIM) -> int:
    """Hash a token to a dimension index."""
    h = hashlib.md5(token.encode()).hexdigest()
    return int(h, 16) % dim


def embed(text: str) -> list[float]:
    """
    Generate embedding vector for text.

    Uses a hash-based bag-of-words approach:
    - Tokenize text
    - Hash each token to a dimension
    - Accumulate counts
    - Normalize to unit vector

    Args:
        text: The text to embed

    Returns:
        Normalized embedding vector of EMBEDDING_DIM dimensions
    """
    if not text or not text.strip():
        return []

    # Initialize vector
    vector = [0.0] * EMBEDDING_DIM

    # Tokenize and hash
    tokens = tokenize(text)
    if not tokens:
        return []

    # Count tokens in each bucket
    for token in tokens:
        idx = hash_token(token)
        vector[idx] += 1.0

    # Also add bigrams for some context
    for i in range(len(tokens) - 1):
        bigram = f"{tokens[i]}_{tokens[i+1]}"
        idx = hash_token(bigram)
        vector[idx] += 0.5  # Weight bigrams less than unigrams

    # L2 normalize
    magnitude = math.sqrt(sum(x * x for x in vector))
    if magnitude > 0:
        vector = [x / magnitude for x in vector]

    return vector


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    Compute cosine similarity between two vectors.

    Args:
        a: First vector
        b: Second vector

    Returns:
        Similarity score between -1 and 1
    """
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts."""
    return [embed(text) for text in texts]


# Optional: API-based embeddings for higher quality
# Uncomment and configure as needed

# def embed_openai(text: str) -> list[float]:
#     """Use OpenAI embeddings API."""
#     import os
#     import httpx
#
#     api_key = os.environ.get("OPENAI_API_KEY")
#     if not api_key:
#         return embed(text)  # Fallback to local
#
#     response = httpx.post(
#         "https://api.openai.com/v1/embeddings",
#         headers={"Authorization": f"Bearer {api_key}"},
#         json={"model": "text-embedding-3-small", "input": text}
#     )
#     return response.json()["data"][0]["embedding"]


if __name__ == "__main__":
    # Test embeddings
    texts = [
        "How to search the web using Python",
        "Web search implementation in code",
        "Making breakfast with eggs",
    ]

    embeddings = embed_batch(texts)

    print("Embedding dimensions:", len(embeddings[0]))
    print("\nSimilarity matrix:")
    for i, t1 in enumerate(texts):
        for j, t2 in enumerate(texts):
            sim = cosine_similarity(embeddings[i], embeddings[j])
            print(f"  [{i}][{j}] {sim:.3f}", end="")
        print(f"  # {t1[:30]}")
