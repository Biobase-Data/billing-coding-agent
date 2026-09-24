"""Locate and verify evidence spans against document text.

Used both to author hand-written fact fixtures (Phase 3) and by the
extraction parser (Phase 4) to reject any fact whose quoted text does not
literally match the document at the given offsets -- the backbone of the
evidence guarantee, applied uniformly regardless of who produced the fact.
"""

from __future__ import annotations


class SpanNotFoundError(ValueError):
    pass


def locate(document_text: str, quoted: str) -> tuple[int, int]:
    """Find the first occurrence of `quoted` in `document_text`.

    Raises rather than guessing if the text isn't there verbatim -- a
    hand-written fixture or an extracted fact that doesn't literally
    appear in the document is a bug, not a fact.
    """
    start = document_text.find(quoted)
    if start == -1:
        raise SpanNotFoundError(f"{quoted!r} not found verbatim in document text")
    return start, start + len(quoted)


def verify(document_text: str, start: int, end: int, quoted: str) -> bool:
    return document_text[start:end] == quoted
