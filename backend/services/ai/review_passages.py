"""Derived, page-local review passages over immutable extraction line anchors.

Grouping is a deterministic presentation heuristic, not a claim that a passage
is a complete clause. Every original nonblank span is retained exactly once and
text is sliced literally from its page. Numbered blocks and blank lines provide
preferred boundaries; bounded fallback groups never join pages or repair text.
Continuation flags make forced splits and physical page boundaries explicit.
"""

import re
from dataclasses import dataclass, replace

from clauseiq_types.source import SourceExtraction, SourcePage, SourceSpan


PASSAGE_VERSION = "source-passages-v1"
MAX_PASSAGE_CHARACTERS = 4_000
MAX_PASSAGE_SPANS = 32
MAX_SINGLE_SPAN_CHARACTERS = 20_000

# Numeric and schedule-style numbering, not agreement-specific heading names.
_NUMBERED_BLOCK = re.compile(r"^\s*(?:\d+(?:\.\d+)*[.)]|\d+(?:\.\d+)+|[A-Z]\d+(?:\.\d+)*[.)])\s+\S")
_SENTENCE_END = re.compile(r"[.!?][\"'\u2019\u201d)\]]*\s*$")
_NEWLINE = re.compile(r"\r\n|\r|\n")


@dataclass(frozen=True)
class ReviewPassage:
    id: str
    source_revision_id: str
    page_number: int
    text: str
    span_ids: tuple[str, ...]
    start: int
    end: int
    continuation_before: bool = False
    continuation_after: bool = False


class PassageConstructionError(ValueError):
    """Safe failure without private source text or invalid field values."""


def _looks_like_heading(span: SourceSpan) -> bool:
    text = span.text.strip()
    # Only affects whether a blank line can separate a heading from its body.
    # False positives keep more context together; they never discard content.
    short_title = (len(text) <= 80 and len(text.split()) <= 10 and text[:1].isupper()
                   and not any(character in text for character in ".,;:"))
    return (len(text) <= 180 and not _SENTENCE_END.search(text)
            and (bool(_NUMBERED_BLOCK.match(text)) or text.isupper() or short_title))


def _blocks(page: SourcePage) -> list[list[SourceSpan]]:
    blocks: list[list[SourceSpan]] = []
    current: list[SourceSpan] = []
    for span in page.spans:
        numbered_boundary = bool(_NUMBERED_BLOCK.match(span.text))
        blank_boundary = bool(current and len(_NEWLINE.findall(page.text[current[-1].end:span.start])) >= 2)
        if current and (numbered_boundary or (blank_boundary and not _looks_like_heading(current[-1]))):
            blocks.append(current)
            current = []
        current.append(span)
    if current:
        blocks.append(current)
    return blocks


def _bounded_groups(block: list[SourceSpan]) -> list[list[SourceSpan]]:
    groups: list[list[SourceSpan]] = []
    offset = 0
    while offset < len(block):
        stop = offset + 1
        while (stop < len(block) and stop - offset < MAX_PASSAGE_SPANS
               and block[stop].end - block[offset].start <= MAX_PASSAGE_CHARACTERS):
            stop += 1
        if stop < len(block):
            # Keep complete sentences when the heuristic block exceeds the cap.
            # The flags still expose this as a split within the original block.
            sentence_stops = [index + 1 for index in range(offset, stop)
                              if _SENTENCE_END.search(block[index].text)]
            if sentence_stops:
                stop = sentence_stops[-1]
        groups.append(block[offset:stop])
        offset = stop
    return groups


def _validate_page(page: SourcePage, seen: set[str]) -> None:
    if page.status != "extracted":
        if page.text.strip() or page.spans:
            raise PassageConstructionError("Unavailable source pages cannot contain anchored text.")
        return
    if not page.text.strip() or not page.spans:
        raise PassageConstructionError("Extracted source pages require exact nonblank anchors.")
    end = 0
    for span in page.spans:
        if (span.id in seen or not span.text.strip() or span.start < end
                or page.text[end:span.start].strip()
                or span.end - span.start != len(span.text)
                or page.text[span.start:span.end] != span.text):
            raise PassageConstructionError("Source passages require ordered, unique, exact anchors.")
        if len(span.text) > MAX_SINGLE_SPAN_CHARACTERS:
            raise PassageConstructionError("A source line exceeds the supported passage size.")
        seen.add(span.id)
        end = span.end
    if page.text[end:].strip():
        raise PassageConstructionError("Source passages cannot omit unanchored text.")


def build_review_passages(extraction: SourceExtraction, source_revision_id: str) -> list[ReviewPassage]:
    """Preserve all anchored text in bounded exact ranges; never mutate extraction.

    A single line longer than the ordinary group limit remains intact up to the
    hard limit, or is rejected. Page-boundary flags are deliberately conservative:
    a neighbouring page may continue or qualify this one, including across an
    unavailable page. They do not assert that the sentences are connected.
    Passage IDs are short request-local references, scoped by source revision.
    """
    if not isinstance(source_revision_id, str) or not source_revision_id.strip():
        raise PassageConstructionError("A source revision is required for review passages.")
    if (extraction.page_count != len(extraction.pages)
            or [page.page_number for page in extraction.pages] != list(range(1, extraction.page_count + 1))):
        raise PassageConstructionError("Source passages require the original page sequence.")
    passages: list[ReviewPassage] = []
    seen: set[str] = set()
    for page in extraction.pages:
        _validate_page(page, seen)
        page_passages: list[ReviewPassage] = []
        for block in _blocks(page):
            groups = _bounded_groups(block)
            for index, group in enumerate(groups):
                start, end = group[0].start, group[-1].end
                page_passages.append(ReviewPassage(
                    id=f"p{page.page_number}_b{len(page_passages) + 1}_v1",
                    source_revision_id=source_revision_id,
                    page_number=page.page_number,
                    text=page.text[start:end],
                    span_ids=tuple(span.id for span in group),
                    start=start,
                    end=end,
                    continuation_before=index > 0,
                    continuation_after=index < len(groups) - 1,
                ))
        # Frozen records are created again rather than mutating extraction or IDs.
        for index, passage in enumerate(page_passages):
            passages.append(replace(
                passage,
                continuation_before=passage.continuation_before or (index == 0 and page.page_number > 1),
                continuation_after=passage.continuation_after or (
                    index == len(page_passages) - 1 and page.page_number < extraction.page_count),
            ))
    return passages
