"""Frozen synthetic retrieval labels and offline exact-source validation."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.ai.review_passages import PASSAGE_VERSION, ReviewPassage, build_review_passages
from services.ai.text_extractor import EXTRACTION_VERSION, TextExtractor


ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT / "backend/fixtures/library_search_evaluations/dataset.json"
FIXTURE_DIRECTORY = ROOT / "tests/fixtures/pdfs"
FIXTURES = frozenset({
    "mutual-nda.pdf", "service-terms-conflict.pdf", "embedded-instructions.pdf",
    "consulting-agreement-5p.pdf", "software-license-12p.pdf", "managed-services-25p.pdf",
    "image-only-scan.pdf",
})
Identity = tuple[str, str, int, str]


class FixtureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FixtureDocument(FixtureModel):
    id: str
    filename: str
    source_revision_id: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    pages: int = Field(ge=1)
    extractable: bool


class SourceAnchor(FixtureModel):
    document_id: str
    source_revision_id: str
    page_number: int = Field(ge=1)
    passage_id: str = Field(pattern=r"^p[1-9]\d*_b[1-9]\d*_v[1-9]\d*$")
    quote: str = Field(min_length=1)

    def identity(self) -> Identity:
        return self.document_id, self.source_revision_id, self.page_number, self.passage_id


class RetrievalCase(FixtureModel):
    id: str
    category: Literal["exact_term", "paraphrase", "multi_document", "exception_near_match", "unanswerable"]
    query: str = Field(min_length=1, max_length=500)
    anchors: list[str]
    rationale: str = Field(min_length=1)


class RetrievalDataset(FixtureModel):
    id: str
    version: str
    purpose: str
    review_basis: str
    extraction_version: str
    passage_version: str
    documents: list[FixtureDocument]
    anchors: dict[str, SourceAnchor]
    cases: list[RetrievalCase] = Field(min_length=20, max_length=30)

    @model_validator(mode="after")
    def validate_references(self):
        documents = {document.id: document for document in self.documents}
        if (len(documents) != len(self.documents)
                or {document.filename for document in self.documents} != FIXTURES
                or len({document.source_revision_id for document in self.documents}) != len(documents)
                or len({case.id for case in self.cases}) != len(self.cases)):
            raise ValueError("Dataset requires distinct allowlisted documents, revisions and cases")
        for anchor in self.anchors.values():
            document = documents.get(anchor.document_id)
            if (document is None or not document.extractable or anchor.page_number > document.pages
                    or anchor.source_revision_id != document.source_revision_id):
                raise ValueError("Relevance anchor must belong to its exact extractable source")
        used = set()
        for case in self.cases:
            if len(set(case.anchors)) != len(case.anchors) or not set(case.anchors).issubset(self.anchors):
                raise ValueError("Case references missing or duplicate relevance anchors")
            if (case.category == "unanswerable") != (not case.anchors):
                raise ValueError("Only unanswerable cases have no relevant source anchors")
            if case.category == "multi_document" and len({self.anchors[key].document_id for key in case.anchors}) < 2:
                raise ValueError("Multi-document cases require at least two relevant documents")
            used.update(case.anchors)
        if used != set(self.anchors):
            raise ValueError("Do not retain unused source anchors")
        return self


@dataclass(frozen=True)
class EvaluationCorpus:
    dataset: RetrievalDataset
    dataset_sha256: str
    documents: list[dict]
    passages: dict[Identity, ReviewPassage]


def load_dataset(path: Path = DATASET_PATH) -> tuple[RetrievalDataset, str]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != path.with_suffix(".sha256").read_text().strip():
        raise ValueError("Frozen dataset hash changed; review and version it deliberately")
    dataset = RetrievalDataset.model_validate(json.loads(raw))
    if dataset.extraction_version != EXTRACTION_VERSION or dataset.passage_version != PASSAGE_VERSION:
        raise ValueError("Extraction or passage version changed; relevance labels need source review")
    return dataset, digest


def validate_anchors(dataset: RetrievalDataset, passages: dict[Identity, ReviewPassage]) -> None:
    for anchor in dataset.anchors.values():
        passage = passages.get(anchor.identity())
        # Whitespace normalization is only for authored PDF line wrapping here;
        # search excerpt/source validation below remains literal and exact.
        normalized_quote = " ".join(anchor.quote.split())
        if passage is None or " ".join(passage.text.split()).count(normalized_quote) != 1:
            raise ValueError("Frozen relevance anchor does not match its exact physical-page passage")
        same_page = [item for identity, item in passages.items() if identity[:3] == anchor.identity()[:3]]
        if sum(" ".join(item.text.split()).count(normalized_quote) for item in same_page) != 1:
            raise ValueError("Relevance anchor is ambiguous on its physical source page")


async def prepare_corpus(path: Path = DATASET_PATH) -> EvaluationCorpus:
    """Read only allowlisted repository PDFs; no settings, credentials or provider."""
    dataset, digest = load_dataset(path)
    documents, passages = [], {}
    for fixture in dataset.documents:
        content = (FIXTURE_DIRECTORY / fixture.filename).read_bytes()
        if hashlib.sha256(content).hexdigest() != fixture.sha256:
            raise ValueError("Fixture PDF hash changed; do not silently relabel the corpus")
        source = await TextExtractor().extract_source(content, fixture.filename)
        if source.page_count != fixture.pages or source.extraction_version != dataset.extraction_version:
            raise ValueError("Fixture physical pages or extraction version changed")
        if fixture.extractable != (source.status == "complete"):
            raise ValueError("Fixture extraction coverage differs from the reviewed dataset")
        document = {
            "id": fixture.id, "filename": fixture.filename, "workspace_id": "synthetic-evaluation",
            "source_revision_id": fixture.source_revision_id, "source_sha256": fixture.sha256,
            "source_status": "stored", "has_pdf_file": True, "extraction_status": source.status,
            "source_extraction": source.model_dump(),
        }
        documents.append(document)
        for passage in build_review_passages(source, fixture.source_revision_id):
            identity = (fixture.id, fixture.source_revision_id, passage.page_number, passage.id)
            passages[identity] = passage
    validate_anchors(dataset, passages)
    return EvaluationCorpus(dataset, digest, documents, passages)
