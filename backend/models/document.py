"""
Document-related models.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
from .common import Clause, RiskSummary
from .source import SourceMetadata


class DocumentReviewSummary(BaseModel):
    kind: Optional[Literal["fixture", "ai"]] = None
    status: Literal["not_started", "ready", "incomplete", "processing", "failed", "interrupted", "unavailable"]
    saved_question_count: int = Field(default=0, ge=0)
    last_activity_at: Optional[str] = None
    can_resume: bool = False


class DocumentListItem(SourceMetadata):
    id: str
    filename: str
    upload_date: str
    contract_type: Optional[str] = None
    rag_processed: Optional[bool] = None
    vector_stored: Optional[bool] = None
    chunk_count: Optional[int] = None
    embedding_model: Optional[str] = None
    last_viewed: Optional[str] = None
    page_count: Optional[int] = Field(default=None, ge=0)
    review_summary: Optional[DocumentReviewSummary] = None


class DocumentListResponse(BaseModel):
    documents: List[DocumentListItem]


class DocumentDetailResponse(SourceMetadata):
    id: str
    filename: str
    upload_date: str
    contract_type: Optional[str] = None
    text: str
    ai_full_summary: Optional[str] = None
    ai_structured_summary: Optional[Dict[str, Any]] = None
    analysis_generation: Optional[Dict[str, Any]] = None
    summary: Optional[str] = None
    clauses: Optional[List[Clause]] = None
    risk_summary: Optional[RiskSummary] = None
    workspace_id: str
    rag_processed: Optional[bool] = None
    vector_stored: Optional[bool] = None
    chunk_count: Optional[int] = None
    chunk_ids: Optional[List[str]] = None
    embedding_model: Optional[str] = None
    rag_processed_at: Optional[str] = None
    storage_service: Optional[str] = None  # "qdrant"
    last_viewed: Optional[str] = None


class AnalyzeDocumentResponse(SourceMetadata):
    id: str
    workspace_id: str
    filename: str
    full_text: str
    summary: str
    ai_structured_summary: Optional[Dict[str, Any]] = None
    analysis_generation: Optional[Dict[str, Any]] = None
    clauses: List[Clause]
    total_clauses: int
    risk_summary: RiskSummary
    contract_type: Optional[str] = None
