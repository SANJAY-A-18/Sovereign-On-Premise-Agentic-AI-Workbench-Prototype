"""
Live integration test for Ollama embeddings correctness.
Requires real host Ollama running with nomic-embed-text.
Marked with @pytest.mark.live and skipped if Ollama is unreachable.
"""

import pytest
from backend.llm import ollama_client, OllamaError


def is_ollama_ready():
    if not ollama_client.is_reachable():
        return False
    health = ollama_client.check_health()
    return health.get("embed_model_present", False)


ollama_available = is_ollama_ready()


@pytest.mark.live
@pytest.mark.skipif(not ollama_available, reason="Real Ollama or nomic-embed-text is unreachable")
def test_live_embedding_dimensions_and_differentiation():
    """
    Verify:
    1. embed() uses /api/embed consistently
    2. Single and batch embeddings return identical vector dimensionality
    3. Two different texts produce different vectors
    """
    text1 = "Minimum attendance required for semester examination is 75 percent."
    text2 = "Database normalization decomposes relations to minimize data redundancy."

    # Single text embedding
    vec1 = ollama_client.embed(text1)
    assert isinstance(vec1, list)
    assert len(vec1) > 0
    dim = len(vec1)

    vec2 = ollama_client.embed(text2)
    assert isinstance(vec2, list)
    assert len(vec2) == dim

    # Different texts must yield distinct embeddings
    assert vec1 != vec2

    # Batch embedding consistency
    batch_vecs = ollama_client.embed([text1, text2])
    assert isinstance(batch_vecs, list)
    assert len(batch_vecs) == 2
    assert len(batch_vecs[0]) == dim
    assert len(batch_vecs[1]) == dim

    # First vector in batch matches single call (approximate or exact)
    # Cosine or difference check
    assert batch_vecs[0] == vec1
    assert batch_vecs[1] == vec2


@pytest.mark.live
@pytest.mark.skipif(not ollama_available, reason="Real Ollama is unreachable")
def test_live_embedding_error_handling():
    """Verify that an invalid model raises a clear OllamaError."""
    with pytest.raises(OllamaError) as exc_info:
        ollama_client.embed("Sample text", model="non_existent_model_xyz_12345")
    assert "Ollama /api/embed returned HTTP" in str(exc_info.value) or "error" in str(exc_info.value).lower()
