"""Page-aware source text, independent of generated analysis or personal work."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


SourceWarning = Literal["no_extractable_text", "page_extraction_failed"]


class SourceSpan(BaseModel):
    """An exact text slice; offsets are page-relative, end-exclusive characters."""

    id: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_offsets(self) -> "SourceSpan":
        if self.end <= self.start or self.end - self.start != len(self.text):
            raise ValueError("Source span offsets must match its text length")
        return self


class SourcePage(BaseModel):
    """Exact extractor output, not a claim about visual or semantic fidelity."""

    page_number: int = Field(ge=1)
    text: str
    status: Literal["extracted", "empty", "failed"]
    spans: list[SourceSpan] = Field(default_factory=list)
    warnings: list[SourceWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_spans(self) -> "SourcePage":
        for span in self.spans:
            if self.text[span.start:span.end] != span.text:
                raise ValueError("Source span must match its page text")
        return self


class SourceExtraction(BaseModel):
    """Versioned extraction of an original file; empty pages do not imply scans."""

    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    extraction_version: str = Field(min_length=1)
    status: Literal["complete", "partial", "unavailable"]
    page_count: int = Field(ge=0)
    pages: list[SourcePage] = Field(default_factory=list)
    warnings: list[SourceWarning] = Field(default_factory=list)
    text: str

    @model_validator(mode="after")
    def validate_page_sequence(self) -> "SourceExtraction":
        if self.page_count != len(self.pages):
            raise ValueError("Source page count must match the page records")
        if [page.page_number for page in self.pages] != list(range(1, self.page_count + 1)):
            raise ValueError("Source page records must retain original page order")
        return self
