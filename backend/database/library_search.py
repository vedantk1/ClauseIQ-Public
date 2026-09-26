"""Allowlisted search projection; never load saved reviews or credentials."""

SEARCH_SOURCE_FIELDS = (
    "id",
    "filename",
    "source_revision_id",
    "source_sha256",
    "source_status",
    "has_pdf_file",
    "extraction_status",
    "source_extraction",
)


def search_source_projection() -> dict[str, int]:
    return {"_id": 0, **{field: 1 for field in SEARCH_SOURCE_FIELDS}}
