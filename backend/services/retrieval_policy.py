"""Pure candidate policies for evaluation; not wired into Library search.

Eligibility is derived metadata, never a source edit. These conservative text
heuristics are not a general PDF-layout classifier or a legal-content detector.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
import math
import re

from services.ai.review_passages import ReviewPassage


SourceIdentity = tuple[str, str, int, str]
POLICY_VERSION = "repeated-header-eligibility-v1"
MIN_REPEATED_PAGES = 3
MIN_PAGE_FRACTION = 0.6
MAX_HEADER_LINES = 4

# Ambiguous wording stays searchable. This intentionally errs on the side of
# keeping furniture rather than suppressing a short or repeated legal clause.
_OPERATIVE = re.compile(
    r"\b(?:shall|must|may|will|can|cannot|agrees?|undertakes?|requires?|required|"
    r"obligations?|liable|liability|permitted|prohibited|pay|paid|payment|unless|"
    r"except|within|without|subject|retains?|owns?|waives?|excludes?)\b", re.I,
)
_NOTICE = re.compile(
    r"(?:\bnot\b[^;:!?]{0,90}\blegal advice[.!]?$|"
    r"^for (?:discussion|evaluation|testing|illustration)(?: purposes)? only[.!]?$|"
    r"^(?:draft|confidential)(?: copy)?[.!]?$)", re.I,
)


def _lines(text: str) -> tuple[str, ...]:
    return tuple(" ".join(line.split()).casefold() for line in text.splitlines() if line.strip())


def _heading_or_notice(line: str) -> bool:
    if len(line) > 180 or _OPERATIVE.search(line) or re.search(r"[\d$£€%]", line):
        return False
    if _NOTICE.search(line):
        return True
    return (len(line.split()) <= 12 and not re.search(r"[.!?;:]", line)
            and not re.search(r"\b(?:no|not|is|are|only|neither|either)\b", line))


def repeated_headers(passages: Mapping[SourceIdentity, ReviewPassage]) -> dict[SourceIdentity, str]:
    """Flag complete, repeated, heading-only first blocks within ONE revision.

At least two leading lines must recur on three pages and 60% of the observed
pages. Mixed body/header blocks and one-block pages stay eligible. Footers
attached to body clauses are intentionally untouched.
"""
    groups: dict[tuple[str, str], dict[int, list[SourceIdentity]]] = defaultdict(lambda: defaultdict(list))
    for identity, passage in passages.items():
        if (identity[1:] != (passage.source_revision_id, passage.page_number, passage.id)
                or not identity[0]):
            raise ValueError("Retrieval source identity mismatch")
        groups[identity[:2]][passage.page_number].append(identity)
    excluded = {}
    for pages in groups.values():
        first = [min(identities, key=lambda item: passages[item].start)
                 for identities in pages.values() if len(identities) > 1]
        prefixes = Counter(_lines(passages[identity].text)[:2] for identity in first)
        minimum = max(MIN_REPEATED_PAGES, math.ceil(len(pages) * MIN_PAGE_FRACTION))
        for identity in first:
            passage = passages[identity]
            lines = _lines(passage.text)
            if (2 <= len(lines) <= MAX_HEADER_LINES
                    # continuation_before also marks a physical page boundary;
                    # repeated complete headers on later pages carry that flag.
                    # A forced split AFTER this block remains ambiguous.
                    and not passage.continuation_after
                    and prefixes[lines[:2]] >= minimum
                    and all(_heading_or_notice(line) for line in lines)):
                excluded[identity] = "repeated_nonoperative_page_header"
    return excluded


def document_diverse(ranking: Sequence[SourceIdentity], limit: int) -> list[SourceIdentity]:
    """Experimental diversity ablation: one best hit per document, then refill.

Never infers relevance or guarantees coverage; irrelevant documents can consume
slots. Compare its tradeoffs before considering it for product search.
"""
    if type(limit) is not int or limit < 1:
        raise ValueError("Result limit must be a positive integer")
    unique = list(dict.fromkeys(ranking))
    chosen, seen = [], set()
    for identity in unique:
        if identity[0] not in seen:
            chosen.append(identity)
            seen.add(identity[0])
            if len(chosen) == limit:
                return chosen
    selected = set(chosen)
    return (chosen + [identity for identity in unique if identity not in selected])[:limit]
