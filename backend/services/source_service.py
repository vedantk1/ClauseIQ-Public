"""Durable, local-only PDF import and recoverable page extraction.

This layer never reads credentials, calls a model, or creates vector data.
Source bytes are immutable; extraction retries operate on the stored original.
"""
import hashlib
import logging
from datetime import datetime, timezone
from uuid import uuid4

from database.service import get_document_service
from services.ai.text_extractor import get_text_extractor
from services.document_service import MAX_FILE_SIZE_BYTES
from services.file_storage_service import GridFSFileStorage

logger = logging.getLogger(__name__)


class SourceError(RuntimeError):
    def __init__(self, code, message, status_code=500, document_id=None):
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.status_code = status_code
        self.document_id = document_id


def source_upload_limit() -> int:
    return min(MAX_FILE_SIZE_BYTES, GridFSFileStorage.MAX_FILE_SIZE)


async def read_pdf_upload(file) -> bytes:
    """Bound actual bytes, including uploads with absent/untrustworthy size metadata."""
    from services.document_service import validate_file

    validate_file(file)
    content = await file.read(source_upload_limit() + 1)
    validate_pdf_bytes(content, file.filename)
    return content


def validate_pdf_bytes(content: bytes, filename: str) -> None:
    if not filename or not filename.lower().endswith(".pdf") or any(
        token in filename for token in ("..", "/", "\\", "\x00")
    ):
        raise SourceError("INVALID_PDF", "Choose a PDF with a valid filename.", 400)
    if len(content) > source_upload_limit():
        raise SourceError("FILE_TOO_LARGE", "The PDF exceeds the supported upload size.", 413)
    if not content or b"%PDF-" not in content[:1024]:
        raise SourceError("INVALID_PDF", "The uploaded file is not a PDF.", 400)


class SourceService:
    def __init__(self, document_service=None, extractor=None):
        self.documents = document_service or get_document_service()
        self.extractor = extractor or get_text_extractor()

    async def _document(self, document_id, workspace_id):
        document = await self.documents.get_document_for_workspace(document_id, workspace_id)
        if not document:
            raise SourceError("DOCUMENT_NOT_FOUND", "Document not found.", 404)
        return document

    async def _update(self, document_id, workspace_id, values):
        if not await self.documents.update_document_data(document_id, workspace_id, values):
            raise SourceError(
                "SOURCE_SAVE_FAILED", "Could not save source processing state. Any stored original has not been deleted.",
                503, document_id,
            )

    async def import_pdf(self, content, filename, workspace_id, content_type="application/pdf"):
        validate_pdf_bytes(content, filename)
        document_id = str(uuid4())
        try:
            return await self._import_pdf(content, filename, workspace_id, document_id)
        except SourceError:
            raise
        except Exception as error:
            logger.error("Source import persistence failed: %s", type(error).__name__)
            raise SourceError(
                "SOURCE_SAVE_FAILED", "Source import could not be completed. Any stored original has not been deleted.",
                503, document_id,
            ) from None

    async def _import_pdf(self, content, filename, workspace_id, document_id):
        document = {
            "id": document_id, "workspace_id": workspace_id, "filename": filename,
            "upload_date": datetime.now(timezone.utc).isoformat(), "text": "",
            "clauses": None, "source_revision_id": str(uuid4()),
            "source_sha256": hashlib.sha256(content).hexdigest(),
            "source_status": "storing", "extraction_status": "pending",
            "analysis_status": "not_started", "has_pdf_file": False,
        }
        await self.documents.save_document_for_workspace(document, workspace_id)
        # Normalise a validated PDF's MIME type; never persist an arbitrary client type.
        stored = await self.documents.store_pdf_file(
            document_id, workspace_id, content, filename, "application/pdf"
        )
        if not stored:
            await self._update(document_id, workspace_id, {"source_status": "storage_failed"})
            raise SourceError(
                "SOURCE_STORAGE_FAILED", "The original PDF could not be confirmed as stored. No AI review was started.",
                503, document_id,
            )
        await self._update(document_id, workspace_id, {"source_status": "stored"})
        return await self.extract(document_id, workspace_id)

    async def extract(self, document_id, workspace_id, restart=False):
        try:
            return await self._extract(document_id, workspace_id, restart)
        except SourceError:
            raise
        except Exception as error:
            logger.error("Source extraction persistence failed: %s", type(error).__name__)
            raise SourceError(
                "SOURCE_SAVE_FAILED", "Source processing state could not be saved. Any stored original has not been deleted.",
                503, document_id,
            ) from None

    async def _extract(self, document_id, workspace_id, restart):
        document = await self._document(document_id, workspace_id)
        # Recover an interrupted status write only from a readable, matching original.
        # A failed upload without an attached file cannot be repaired by extraction.
        if (document.get("source_revision_id") and document.get("source_status") in {"storing", "storage_failed"}
                and document.get("has_pdf_file")):
            stored = await self.documents.get_pdf_file(document_id, workspace_id)
            if (stored and isinstance(stored.get("content"), bytes)
                    and hashlib.sha256(stored["content"]).hexdigest() == document.get("source_sha256")):
                await self.documents.update_document_if(document_id, workspace_id, {
                    "source_revision_id": document["source_revision_id"],
                    "source_status": document["source_status"], "pdf_file_id": document.get("pdf_file_id"),
                }, {"source_status": "stored"})
                document = await self._document(document_id, workspace_id)
        if not document.get("source_revision_id") or document.get("source_status") != "stored":
            raise SourceError("SOURCE_NOT_AVAILABLE", "This document has no confirmed source revision.", 409, document_id)
        # Published extraction is immutable. Repeated requests return the same snapshot.
        if document.get("source_extraction") is not None:
            return document
        previous_status = document.get("extraction_status")
        if previous_status == "processing" and not restart:
            raise SourceError("EXTRACTION_IN_PROGRESS", "Source extraction is already in progress.", 409, document_id)
        if previous_status not in {"pending", "failed", "processing"}:
            raise SourceError("EXTRACTION_STATE_INVALID", "Source extraction cannot start in this state.", 409, document_id)
        attempt = str(uuid4())
        expected = {
            "source_revision_id": document["source_revision_id"],
            "extraction_status": previous_status,
            "extraction_attempt_id": document.get("extraction_attempt_id"),
            "source_extraction": None,
        }
        claimed = await self.documents.update_document_if(document_id, workspace_id, expected, {
            "extraction_status": "processing", "extraction_attempt_id": attempt,
            "extraction_started_at": datetime.now(timezone.utc).isoformat(),
            "extraction_error": None,
        })
        if not claimed:
            raise SourceError("EXTRACTION_CONFLICT", "Source processing changed. Reload before retrying.", 409, document_id)
        fence = {"source_revision_id": document["source_revision_id"], "extraction_attempt_id": attempt,
                 "extraction_status": "processing"}
        try:
            stored = await self.documents.get_pdf_file(document_id, workspace_id)
            if not stored or not isinstance(stored.get("content"), bytes):
                raise SourceError("SOURCE_READ_FAILED", "The stored original could not be read.", 503, document_id)
            content = stored["content"]
            if hashlib.sha256(content).hexdigest() != document["source_sha256"]:
                raise SourceError("SOURCE_INTEGRITY_FAILED", "The stored original does not match this source revision.", 409, document_id)
            extraction = await self.extractor.extract_source(content, document["filename"])
        except Exception as error:
            code = error.code if isinstance(error, SourceError) else "PDF_EXTRACTION_FAILED"
            updated = await self.documents.update_document_if(document_id, workspace_id, fence, {
                "extraction_status": "failed", "extraction_error": code,
            })
            if not updated:
                raise SourceError("EXTRACTION_CONFLICT", "This extraction was superseded. Reload the current source.", 409, document_id)
            logger.warning("Source extraction failed: %s", type(error).__name__)
            # Import succeeded even if text extraction could not; the PDF remains readable.
            return await self._document(document_id, workspace_id)
        updated = await self.documents.update_document_if(document_id, workspace_id, fence, {
            "source_extraction": extraction.model_dump(), "text": extraction.text,
            "extraction_status": extraction.status, "extraction_error": None,
        })
        if not updated:
            raise SourceError("EXTRACTION_CONFLICT", "This extraction was superseded. Reload the current source.", 409, document_id)
        return await self._document(document_id, workspace_id)
