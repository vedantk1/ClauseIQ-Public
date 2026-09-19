"""Content-free Mongo projection and conservative Library display summaries.

This is not a second review validator. The workspace still validates complete
saved output and evidence on opening; listing must not load that output or text.
"""
from datetime import datetime, timezone


LIBRARY_FIELDS = (
    "id", "filename", "upload_date", "contract_type", "rag_processed",
    "vector_stored", "chunk_count", "embedding_model", "last_viewed",
    "source_revision_id", "source_sha256", "source_status", "extraction_status",
    "extraction_error", "analysis_status",
)
RUN_STATUSES = {"ready", "incomplete", "processing", "failed", "interrupted"}


def _array(value):
    return {"$cond": [{"$isArray": value}, value, []]}


def _entries(value):
    return {"$objectToArray": {"$cond": [{"$eq": [{"$type": value}, "object"]}, value, {}]}}


def library_projection():
    """Use expressions in Mongo, not Python, to omit large/private nested text."""
    return {
        "_id": 0, **{key: 1 for key in LIBRARY_FIELDS},
        "page_count": "$source_extraction.page_count",
        "_library": {
            "has_pdf_file": "$has_pdf_file",
            "state_type": {"$type": "$review_workspace"},
            "document_id": "$review_workspace.document_id",
            "source_revision_id": "$review_workspace.source_revision_id",
            "revision": "$review_workspace.revision",
            "runs_type": {"$type": "$review_workspace.runs"},
            "runs": {"$map": {"input": _array("$review_workspace.runs"), "as": "run", "in": {
                **{key: f"$$run.{key}" for key in (
                    "id", "kind", "source_revision_id", "status", "created_at", "completed_at",
                )},
                "type": {"$type": "$$run"},
                "status_type": {"$type": "$$run.status"},
                "generation_type": {"$type": "$$run.generation"},
                "coverage_type": {"$type": "$$run.coverage"},
                "omitted_count": {"$size": _array("$$run.coverage.omitted_pages")},
                "omitted_type": {"$type": "$$run.coverage.omitted_pages"},
                "failure_type": {"$type": "$$run.failure"},
                "overview_count": {"$size": _array("$$run.overview_items")},
                "overview_type": {"$type": "$$run.overview_items"},
                "has_overview": {"$ne": [{"$ifNull": ["$$run.overview", ""]}, ""]},
                "findings_type": {"$type": "$$run.findings"},
                "finding_ids": {"$map": {"input": _array("$$run.findings"), "as": "finding", "in": "$$finding.id"}},
            }}},
            "personal_type": {"$type": "$review_workspace.personal"},
            "personal": {"$map": {"input": _entries("$review_workspace.personal"), "as": "personal", "in": {
                "run_id": "$$personal.k", "type": {"$type": "$$personal.v"},
                "questions_type": {"$type": "$$personal.v.saved_questions"},
                "questions": {"$map": {"input": _entries("$$personal.v.saved_questions"), "as": "question", "in": {
                    "finding_id": "$$question.k", "type": {"$type": "$$question.v"},
                    "saved_at": "$$question.v.saved_at", "id": "$$question.v.id",
                    # Counts expose no wording, but malformed question records
                    # must not be advertised as confirmed saved work.
                    "text_type": {"$type": "$$question.v.text"},
                    "text_length": {"$strLenCP": {"$cond": [
                        {"$eq": [{"$type": "$$question.v.text"}, "string"]}, "$$question.v.text", "",
                    ]}},
                }}},
            }}},
        },
    }


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _latest_activity(values):
    timestamps = [parsed for value in values if (parsed := _timestamp(value)) is not None]
    return max(timestamps).isoformat() if timestamps else None


def _id(value):
    return isinstance(value, str) and 0 < len(value) <= 128 and all(c.isascii() and (c.isalnum() or c in "_-") for c in value)


def review_summary(document, metadata):
    """Derive display state using the same final-array-run default as workspace.

    Unknown/corrupt projected metadata becomes unavailable, never a ready badge
    or an automatic fallback to an older successful review.
    """
    summary = {"kind": None, "status": "unavailable", "saved_question_count": 0,
               "last_activity_at": _latest_activity([document.get("last_viewed")]), "can_resume": False}
    if not isinstance(metadata, dict):
        return summary
    if metadata.get("state_type") in ("missing", "null"):
        summary["status"] = "not_started"
        return summary
    if (metadata.get("state_type") != "object" or metadata.get("document_id") != document.get("id")
            or not _id(document.get("source_revision_id"))
            or metadata.get("source_revision_id") != document["source_revision_id"]
            or document.get("source_status") != "stored" or metadata.get("has_pdf_file") is not True
            or type(metadata.get("revision")) is not int or metadata["revision"] < 0
            or metadata.get("runs_type") not in ("array", "missing")
            or metadata.get("personal_type") not in ("object", "missing")):
        return summary
    runs = metadata.get("runs", [])
    personal = metadata.get("personal", [])
    if not isinstance(runs, list) or not isinstance(personal, list) or len(runs) > 100 or len(personal) > 100:
        return summary
    run_ids = set()
    activity = [document.get("last_viewed")]
    findings_by_run = {}
    for run in runs:
        if not isinstance(run, dict):
            return summary
        run_id = run.get("id")
        kind = run.get("kind")
        status = "ready" if kind == "fixture" and run.get("status_type") == "missing" else run.get("status")
        finding_ids = run.get("finding_ids", [])
        if (run.get("type") != "object" or not _id(run_id) or run_id in run_ids
                or kind not in ("fixture", "ai") or run.get("source_revision_id") != document["source_revision_id"]
                or not isinstance(run.get("created_at"), str) or not isinstance(status, str) or status not in RUN_STATUSES
                or run.get("findings_type") not in ("array", "missing")
                or not isinstance(finding_ids, list) or len(finding_ids) > 100
                or any(not _id(item) for item in finding_ids) or len(set(finding_ids)) != len(finding_ids)):
            return summary
        if kind == "ai":
            if (run.get("generation_type") != "object" or run.get("coverage_type") != "object"
                    or run.get("omitted_type") != "array" or run.get("overview_type") not in ("array", "missing")
                    or (status != "processing" and not isinstance(run.get("completed_at"), str))
                    or (status == "ready" and (run.get("failure_type") not in ("null", "missing")
                                              or run.get("omitted_count") != 0 or not run.get("overview_count")))
                    or (status in ("processing", "failed", "interrupted")
                        and (finding_ids or run.get("overview_count") or run.get("has_overview")))):
                return summary
        run_ids.add(run_id)
        findings_by_run[run_id] = set(finding_ids)
        activity.extend([run.get("created_at"), run.get("completed_at")])
    questions_by_run = {}
    for entry in personal:
        if (not isinstance(entry, dict) or entry.get("type") != "object"
                or not _id(entry.get("run_id")) or entry["run_id"] not in run_ids
                or entry.get("questions_type") not in ("object", "missing")):
            return summary
        questions = entry.get("questions", [])
        if not isinstance(questions, list) or len(questions) > 100:
            return summary
        for question in questions:
            if (not isinstance(question, dict) or question.get("type") != "object"
                    or not _id(question.get("finding_id")) or question["finding_id"] not in findings_by_run[entry["run_id"]]
                    or not _id(question.get("id")) or not isinstance(question.get("saved_at"), str)
                    or question.get("text_type") != "string" or type(question.get("text_length")) is not int
                    or not 1 <= question["text_length"] <= 5000):
                return summary
            activity.append(question["saved_at"])
        questions_by_run[entry["run_id"]] = len(questions)
    summary["last_activity_at"] = _latest_activity(activity)
    if not runs:
        summary["status"] = "not_started"
        return summary
    latest = runs[-1]
    status = "ready" if latest["kind"] == "fixture" and latest.get("status_type") == "missing" else latest["status"]
    summary.update(kind=latest["kind"], status=status,
                   saved_question_count=questions_by_run.get(latest["id"], 0),
                   can_resume=status in ("ready", "incomplete"))
    return summary


def library_item(projected):
    """Explicit allowlist prevents intermediate projection metadata escaping."""
    item = {key: projected[key] for key in LIBRARY_FIELDS if key in projected}
    count = projected.get("page_count")
    item["page_count"] = count if type(count) is int and count >= 0 else None
    item["review_summary"] = review_summary(item, projected.get("_library"))
    return item
