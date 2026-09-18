"""Public source responses omit storage pointers and processing-fence tokens."""
from typing import Literal, Optional

from pydantic import BaseModel
from clauseiq_types.source import SourceExtraction


class SourceMetadata(BaseModel):
    source_revision_id: Optional[str] = None
    source_sha256: Optional[str] = None
    source_status: Optional[Literal["storing", "stored", "storage_failed"]] = None
    extraction_status: Optional[Literal["pending", "processing", "complete", "partial", "unavailable", "failed"]] = None
    extraction_error: Optional[str] = None
    analysis_status: Optional[Literal["not_started", "processing", "ready", "failed"]] = None


class DocumentSourceResponse(SourceMetadata):
    id: str
    source_extraction: Optional[SourceExtraction] = None


class ExtractionRequest(BaseModel):
    # Explicitly supersede an interrupted local extraction; never retries paid AI.
    restart: bool = False
