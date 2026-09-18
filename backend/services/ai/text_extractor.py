"""Extract source text and stable, page-relative anchors without AI calls."""

import asyncio
import hashlib
from io import BytesIO

import pdfplumber

from clauseiq_types.source import SourceExtraction, SourcePage, SourceSpan


EXTRACTION_VERSION = f"pdfplumber:{pdfplumber.__version__}:page-lines-v1"


def _line_spans(text: str, content_sha256: str, page_number: int) -> list[SourceSpan]:
    """Anchor nonblank lines, without normalizing or reordering source text."""
    spans = []
    offset = 0
    for line in text.splitlines(keepends=True):
        line_text = line.rstrip("\r\n")
        if line_text.strip():
            end = offset + len(line_text)
            identity = f"{content_sha256}:{EXTRACTION_VERSION}:{page_number}:{offset}:{end}"
            spans.append(SourceSpan(
                id=f"src_{hashlib.sha256(identity.encode('utf-8')).hexdigest()}",
                start=offset,
                end=end,
                text=line_text,
            ))
        offset += len(line)
    return spans


class TextExtractor:
    """PDF extraction with a flattened-text compatibility entry point."""

    async def extract_text(self, file_content: bytes, filename: str) -> str:
        """Retain the existing text result and no-text error for legacy callers."""
        source = await self.extract_source(file_content, filename)
        if any(page.status == "failed" for page in source.pages):
            # Text-only callers cannot display coverage gaps and must not hide failures.
            raise ValueError("Could not extract text from all PDF pages")
        if not source.text:
            raise ValueError("No text could be extracted from PDF")
        return source.text

    async def extract_source(self, file_content: bytes, filename: str) -> SourceExtraction:
        """Extract page records off the event loop, without writing temporary PDFs."""
        if not filename.lower().endswith(".pdf"):
            raise ValueError("Unsupported file format")
        return await asyncio.to_thread(self._extract_pdf_source, file_content)

    async def _extract_pdf_text(self, file_content: bytes) -> str:
        """Retain the former PDF-only helper for compatibility."""
        return await self.extract_text(file_content, "document.pdf")

    @staticmethod
    def _extract_pdf_source(file_content: bytes) -> SourceExtraction:
        content_sha256 = hashlib.sha256(file_content).hexdigest()
        pages = []
        try:
            with pdfplumber.open(BytesIO(file_content)) as pdf:
                for page_number, page in enumerate(pdf.pages, start=1):
                    try:
                        page_text = page.extract_text() or ""
                    except Exception:
                        # Neither exception details nor source fragments belong in warnings.
                        pages.append(SourcePage(
                            page_number=page_number,
                            text="",
                            status="failed",
                            warnings=["page_extraction_failed"],
                        ))
                        continue
                    has_text = bool(page_text.strip())
                    pages.append(SourcePage(
                        page_number=page_number,
                        text=page_text,
                        status="extracted" if has_text else "empty",
                        spans=_line_spans(page_text, content_sha256, page_number),
                        warnings=[] if has_text else ["no_extractable_text"],
                    ))
        except Exception:
            # Broken/encrypted containers cannot provide a reliable page inventory.
            raise ValueError("Could not read PDF") from None

        # Preserve the original extractor's newline joining and outer stripping.
        text = "\n".join(page.text for page in pages if page.text).strip()
        warnings = list(dict.fromkeys(warning for page in pages for warning in page.warnings))
        if not text and "no_extractable_text" not in warnings:
            warnings.append("no_extractable_text")
        status = (
            "unavailable" if not text
            else "complete" if all(page.status == "extracted" for page in pages)
            else "partial"
        )
        return SourceExtraction(
            content_sha256=content_sha256,
            extraction_version=EXTRACTION_VERSION,
            status=status,
            page_count=len(pages),
            pages=pages,
            warnings=warnings,
            text=text,
        )


# Global text extractor instance
_text_extractor = None


def get_text_extractor() -> TextExtractor:
    """Get the global text extractor instance."""
    global _text_extractor
    if _text_extractor is None:
        _text_extractor = TextExtractor()
    return _text_extractor
