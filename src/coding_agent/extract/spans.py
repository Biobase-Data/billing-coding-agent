"""Locate evidence spans in a Case's narrative text.

The model is asked for the quoted text but never trusted for character
offsets -- LLMs are unreliable at raw character arithmetic, and there is
nothing to gain by asking: what needs verifying is whether the quote is
real, not whether the model can count. `locate` finds the quote itself
in the cited section's text (first occurrence); `SpanNotFoundError` is
raised, never guessed past, if it isn't there verbatim.
"""

from __future__ import annotations

from coding_agent.normalize.case import Case, EvidenceSpan, NarrativeKind


class SpanNotFoundError(ValueError):
    pass


def locate(
    case: Case, *, section: NarrativeKind, quoted: str
) -> EvidenceSpan:
    """Find `quoted`'s first occurrence in `case`'s section of that
    kind and return a verified EvidenceSpan.

    Raises SpanNotFoundError if the section is absent on this case or
    the quoted text is not found verbatim within it.
    """
    narrative_section = case.section(section)
    if narrative_section is None or not narrative_section.text.is_present:
        raise SpanNotFoundError(f"case has no {section.value} section text to search")

    text = narrative_section.text.value
    start = text.find(quoted)
    if start == -1:
        raise SpanNotFoundError(f"{quoted!r} not found verbatim in {section.value} section")

    return EvidenceSpan(
        document_id=case.source_document_id,
        section=section,
        start=start,
        end=start + len(quoted),
        quoted=quoted,
    )
