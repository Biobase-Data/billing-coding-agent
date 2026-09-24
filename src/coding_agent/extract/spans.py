"""Locate evidence spans in a Case's narrative text.

The model is asked for the quoted text but never trusted for character
offsets -- LLMs are unreliable at raw character arithmetic, and there is
nothing to gain by asking: what needs verifying is whether the quote is
real, not whether the model can count. `locate` finds the quote itself
in the cited section's text (first occurrence); `SpanNotFoundError` is
raised, never guessed past, if it isn't there verbatim.

"Verbatim" is whitespace-tolerant, not byte-exact: real PDF text
extraction preserves a mid-sentence line wrap as a literal newline
inside the source text, but a model reproducing a "verbatim" quote of
that sentence naturally normalizes the internal line break to a plain
space -- it has no way to know, or reason to care, that the rendered
page happened to wrap there. Treating that as a hallucination and
rejecting the whole extraction over it would be punishing a formatting
difference, not catching an untrustworthy claim. The fallback below only
ever lets *runs of whitespace* match different runs of whitespace; every
non-whitespace character in the model's quote must still match exactly,
and the `EvidenceSpan` this returns always carries the *real* source
substring (offsets and text alike) as `quoted`, never the model's
normalized version -- so `Case.resolve_span`'s later re-verification
still holds.
"""

from __future__ import annotations

import re

from coding_agent.normalize.case import Case, EvidenceSpan, NarrativeKind


class SpanNotFoundError(ValueError):
    pass


def _whitespace_tolerant_pattern(quoted: str) -> re.Pattern[str]:
    parts = re.split(r"(\s+)", quoted)
    pattern = "".join(
        r"\s+" if part.strip() == "" and part != "" else re.escape(part) for part in parts
    )
    return re.compile(pattern)


def locate(
    case: Case, *, section: NarrativeKind, quoted: str
) -> EvidenceSpan:
    """Find `quoted`'s first occurrence in `case`'s section of that
    kind and return a verified EvidenceSpan.

    Raises SpanNotFoundError if the section is absent on this case or
    the quoted text is not found (allowing whitespace-only differences,
    per this module's docstring) within it.
    """
    narrative_section = case.section(section)
    if narrative_section is None or not narrative_section.text.is_present:
        raise SpanNotFoundError(f"case has no {section.value} section text to search")

    text = narrative_section.text.value

    start = text.find(quoted)
    if start != -1:
        return EvidenceSpan(
            document_id=case.source_document_id,
            section=section,
            start=start,
            end=start + len(quoted),
            quoted=quoted,
        )

    match = _whitespace_tolerant_pattern(quoted).search(text)
    if match is None:
        raise SpanNotFoundError(f"{quoted!r} not found verbatim in {section.value} section")

    return EvidenceSpan(
        document_id=case.source_document_id,
        section=section,
        start=match.start(),
        end=match.end(),
        quoted=text[match.start() : match.end()],
    )
