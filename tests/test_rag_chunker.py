"""
Unit tests for TextChunker in backend/rag.py.
Verifies boundary preservation:
- Never splits words mid-word
- Prefers sentence, line, and paragraph boundaries
- Honors chunk_size and chunk_overlap
"""

import pytest
from backend.rag import TextChunker


def test_chunker_never_splits_mid_word():
    text = (
        "Undergraduate students are eligible for a maximum loan duration of sixteen calendar days. "
        "Graduate researchers and faculty members enjoy extended borrowing privileges up to thirty days. "
        "Overdue fines accrue daily at the prescribed institutional rate."
    )
    words_in_text = set(text.replace(".", "").split())

    chunks = TextChunker.chunk_text(text, chunk_size=80, chunk_overlap=20)
    assert len(chunks) > 1

    for c in chunks:
        chunk_words = c.replace(".", "").split()
        for w in chunk_words:
            assert w in words_in_text, f"Word '{w}' was split or corrupted in chunk: '{c}'"


def test_chunker_prefers_sentence_boundaries():
    text = (
        "First sentence ends here. Second sentence starts right here and continues for some length. "
        "Third sentence is also present in this document."
    )
    chunks = TextChunker.chunk_text(text, chunk_size=55, chunk_overlap=15)
    # The first chunk should end on the period of the first sentence
    assert chunks[0].endswith(".")
    assert chunks[0] == "First sentence ends here."


def test_chunker_prefers_paragraph_and_line_boundaries():
    text = (
        "Section 1: General Regulations.\n\n"
        "Clause 1.1: All students must register each semester.\n"
        "Clause 1.2: Identity badges must be displayed on campus.\n\n"
        "Section 2: Examination Conduct."
    )
    chunks = TextChunker.chunk_text(text, chunk_size=70, chunk_overlap=20)
    # Chunk 0 should break cleanly at a paragraph or line boundary
    assert chunks[0].endswith(".")
    for c in chunks:
        # No line should be cut in the middle of a word
        words = c.replace(":", "").replace(".", "").split()
        assert "Regulati" not in words
        assert "Gener" not in words


def test_chunker_respects_parameters():
    text = "Word " * 200
    c1 = TextChunker.chunk_text(text, chunk_size=100, chunk_overlap=20)
    c2 = TextChunker.chunk_text(text, chunk_size=300, chunk_overlap=50)
    c3 = TextChunker.chunk_text(text, chunk_size=500, chunk_overlap=50)

    # Larger chunk sizes produce fewer chunks
    assert len(c1) > len(c2) > len(c3)


def test_chunker_empty_and_short_text():
    assert TextChunker.chunk_text("") == []
    assert TextChunker.chunk_text("   \n\t  ") == []

    short = "Hello world."
    assert TextChunker.chunk_text(short, chunk_size=100) == [short]


def test_chunker_unbroken_long_word():
    long_token = "A" * 150
    chunks = TextChunker.chunk_text(long_token, chunk_size=50, chunk_overlap=10)
    # Should not hang or infinite loop; takes the unbroken token
    assert len(chunks) == 1
    assert chunks[0] == long_token
