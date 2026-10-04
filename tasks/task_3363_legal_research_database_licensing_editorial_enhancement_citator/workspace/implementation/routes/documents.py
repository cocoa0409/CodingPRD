"""Primary-law document routes (PRD 3.1, 3.2): ingest, list, read,
citing-reference lookup, publish, and citator override."""

from flask import Blueprint, request

from constants import (
    CITATOR_SIGNALS,
    DEPTHS,
    DOCUMENT_TYPES,
    DIRECTIONS,
    INGESTION_STATUSES,
    REFERENCE_STATUSES,
    ROLES,
    SOURCE_TYPES,
    TREATMENTS,
    VISIBILITY_STATUSES,
)
from db import iso_now, stamp_new, store, touch
from errors import raise_err
from middleware import require_roles
from response import list_response, ok_object, parse_pagination
from serializers import serialize_document, serialize_reference
from services.citator import compute_citator, normalize_citation, recompute_citator
from util import get_body, opt_enum_query, req_date, req_enum, req_int, req_str

bp = Blueprint("documents", __name__)

ANY_ROLE = tuple(ROLES)


def _get_document_or_404(document_id):
    doc = store.documents.get(document_id)
    if doc is None:
        raise_err("ERR_DOCUMENT_NOT_FOUND", "document %s does not exist" % document_id)
    return doc


@bp.post("/legal-research/documents")
@require_roles("ContentIngester")
def create_document():
    body = get_body()
    source_type = req_enum(body, "source_type", SOURCE_TYPES)
    jurisdiction_code = req_str(body, "jurisdiction_code")
    document_type = req_enum(body, "document_type", DOCUMENT_TYPES)
    title = req_str(body, "title")
    raw_citation_string = req_str(body, "raw_citation_string")
    decision_date = req_date(body, "decision_date")

    doc = stamp_new({
        "source_type": source_type,
        "jurisdiction_code": jurisdiction_code,
        "document_type": document_type,
        "title": title,
        "raw_citation_string": raw_citation_string,
        "normalized_citation": None,
        "decision_date": decision_date.isoformat(),
        "ingestion_status": "RECEIVED",
        "visibility_status": "PUBLIC",
        "citator_score": 0,
        "citator_signal": "GREEN",
        "editorial_override_signal": None,
        "editorial_override_rationale": None,
        "published_at": None,
    })
    store.documents[doc["id"]] = doc
    return ok_object(serialize_document(doc), 201)


@bp.get("/legal-research/documents")
@require_roles(*ANY_ROLE)
def list_documents():
    f_source = opt_enum_query("source_type", SOURCE_TYPES)
    f_jurisdiction = request.args.get("jurisdiction_code")
    f_ingestion = opt_enum_query("ingestion_status", INGESTION_STATUSES)
    f_visibility = opt_enum_query("visibility_status", VISIBILITY_STATUSES)

    rows = list(store.documents.values())
    if f_source is not None:
        rows = [d for d in rows if d["source_type"] == f_source]
    if f_jurisdiction is not None:
        rows = [d for d in rows if d["jurisdiction_code"] == f_jurisdiction]
    if f_ingestion is not None:
        rows = [d for d in rows if d["ingestion_status"] == f_ingestion]
    if f_visibility is not None:
        rows = [d for d in rows if d["visibility_status"] == f_visibility]
    else:
        # REMOVED documents are hidden unless explicitly requested (PRD 2.10).
        rows = [d for d in rows if d["visibility_status"] != "REMOVED"]
    return list_response(rows, serialize_document)


@bp.get("/legal-research/documents/<document_id>")
@require_roles(*ANY_ROLE)
def get_document(document_id):
    doc = _get_document_or_404(document_id)
    if doc["visibility_status"] == "REMOVED":
        raise_err("ERR_DOCUMENT_REMOVED", "document %s has been removed" % document_id)
    return ok_object(serialize_document(doc))


@bp.get("/legal-research/documents/<document_id>/citing-references")
@require_roles(*ANY_ROLE)
def list_citing_references(document_id):
    # Shape validation (priority 5) precedes identifier resolution (priority 6).
    direction = opt_enum_query("direction", DIRECTIONS)
    f_status = opt_enum_query("status", REFERENCE_STATUSES)
    parse_pagination()

    doc = _get_document_or_404(document_id)
    if doc["visibility_status"] == "REMOVED":
        raise_err("ERR_DOCUMENT_REMOVED", "document %s has been removed" % document_id)

    rows = []
    for ref in store.references.values():
        if direction == "FROM":
            if ref["citing_document_id"] != document_id:
                continue
        elif direction == "TO":
            if ref["cited_document_id"] != document_id:
                continue
        else:
            if ref["citing_document_id"] != document_id and ref["cited_document_id"] != document_id:
                continue
        if f_status is not None and ref["status"] != f_status:
            continue
        rows.append(ref)
    return list_response(rows, serialize_reference)


@bp.post("/legal-research/documents/<document_id>/publish")
@require_roles("ContentIngester")
def publish_document(document_id):
    body = get_body()

    # Shape validation (priority 5).
    references = body.get("references")
    if not isinstance(references, list):
        raise_err("ERR_INVALID_REQUEST", "field 'references' is required and must be a list")
    for entry in references:
        if not isinstance(entry, dict):
            raise_err("ERR_INVALID_REQUEST", "each references entry must be an object")
        req_str(entry, "cited_document_id")
        req_enum(entry, "treatment", TREATMENTS)
        req_enum(entry, "depth", DEPTHS)

    # Existence (priority 6): path document, then payload entries in order.
    doc = _get_document_or_404(document_id)
    for entry in references:
        if entry["cited_document_id"] not in store.documents:
            raise_err(
                "ERR_DOCUMENT_NOT_FOUND",
                "cited document %s does not exist" % entry["cited_document_id"],
            )

    # State (priority 18): publish requires ingestion_status == RECEIVED.
    if doc["ingestion_status"] != "RECEIVED":
        raise_err("ERR_INVALID_STATE", "document %s is already published" % document_id)

    # Business constraints in pinned order: duplicate citation (29), then
    # self-citation (30), then citation-target publication (31).
    normalized = normalize_citation(doc["raw_citation_string"])
    for other in store.documents.values():
        if (
            other["id"] != doc["id"]
            and other["normalized_citation"] is not None
            and other["normalized_citation"] == normalized
        ):
            raise_err("ERR_DUPLICATE_CITATION", "normalized citation '%s' already exists" % normalized)
    for entry in references:
        if entry["cited_document_id"] == doc["id"]:
            raise_err("ERR_SELF_CITATION", "a document cannot cite itself")
    for entry in references:
        target = store.documents[entry["cited_document_id"]]
        if target["ingestion_status"] != "PUBLISHED":
            raise_err(
                "ERR_CITATION_TARGET_NOT_PUBLISHED",
                "cited document %s is not published" % entry["cited_document_id"],
            )

    # Commit the transition and fan out the publish cascade.
    now = iso_now()
    doc["normalized_citation"] = normalized
    doc["ingestion_status"] = "PUBLISHED"
    doc["published_at"] = now
    touch(doc)

    cited_ids = []
    for entry in references:
        ref = stamp_new({
            "citing_document_id": doc["id"],
            "cited_document_id": entry["cited_document_id"],
            "treatment": entry["treatment"],
            "depth": entry["depth"],
            "status": "ACTIVE",
            "deactivated_by_order_id": None,
        })
        store.references[ref["id"]] = ref
        if entry["cited_document_id"] not in cited_ids:
            cited_ids.append(entry["cited_document_id"])
    for cited_id in cited_ids:
        recompute_citator(store.documents[cited_id])

    return ok_object(serialize_document(doc), 200)


@bp.post("/legal-research/documents/<document_id>/citator-override")
@require_roles("CitatorAnalyst")
def citator_override(document_id):
    body = get_body()
    override_signal = req_enum(body, "override_signal", CITATOR_SIGNALS)
    rationale = body.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        raise_err("ERR_INVALID_REQUEST", "field 'rationale' must be a string")
    expected_version = req_int(body, "expected_document_version")

    doc = _get_document_or_404(document_id)

    # OCC guard (priority 35): the write legitimately supersedes any earlier
    # override, so only the stale-version check protects it.
    if expected_version != doc["version"]:
        raise_err("ERR_STALE_VERSION", "expected_document_version %s does not match current version %s" % (expected_version, doc["version"]))

    doc["editorial_override_signal"] = override_signal
    doc["editorial_override_rationale"] = rationale
    score, signal = compute_citator(doc)
    doc["citator_score"] = score
    doc["citator_signal"] = signal
    touch(doc)
    return ok_object(serialize_document(doc), 200)
