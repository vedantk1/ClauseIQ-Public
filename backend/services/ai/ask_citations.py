"""Recognize explicit inline passage IDs without editing generated prose."""

import re

from clauseiq_types.review import ReviewAskInlineCitation


PASSAGE_ID = r"p[1-9]\d*_b[1-9]\d*_v[1-9]\d*"
INLINE_GROUP = re.compile(r"\[\s*" + PASSAGE_ID + r"(?:\s*[,;]\s*" + PASSAGE_ID + r")*\s*\]")
INLINE_ID = re.compile(PASSAGE_ID)


def bind_inline_citations(text: str, resolved_passage_ids: list[str]) -> list[ReviewAskInlineCitation]:
    """Bind only IDs whose evidence was already resolved for this paragraph.

    The caller supplies canonical evidence IDs in the resolver's unchanged order.
    An ID elsewhere in the source or another paragraph is not enough. Unknown or
    unsupported syntax remains literal/unlinked; this is not a semantic check.
    """
    mentioned = {identifier for group in INLINE_GROUP.finditer(text) for identifier in INLINE_ID.findall(group[0])}
    return [
        ReviewAskInlineCitation(passage_id=passage_id, evidence_index=index)
        for index, passage_id in enumerate(resolved_passage_ids) if passage_id in mentioned
    ]
