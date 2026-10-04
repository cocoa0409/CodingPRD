"""Headnote editorial workflow routes (PRD 3.3)."""

from flask import Blueprint, g, request

from constants import HEADNOTE_STATUSES, ROLES, TOPIC_CODES
from db import stamp_new, store, touch
from errors import raise_err
from middleware import require_roles
from response import list_response, ok_object
from serializers import serialize_headnote
from util import get_body, opt_enum_query, opt_str, req_enum, req_str

bp = Blueprint("headnotes", __name__)

ANY_ROLE = tuple(ROLES)


def _get_headnote_or_404(headnote_id):
    headnote = store.headnotes.get(headnote_id)
    if headnote is None:
        raise_err("ERR_HEADNOTE_NOT_FOUND", "headnote %s does not exist" % headnote_id)
    return headnote


def _document_gates(headnote):
    """Editorial document gates, in cascade order: not-published (19) before
    sealed (20). REMOVED visibility counts as sealed here."""
    doc = store.documents[headnote["document_id"]]
    if doc["ingestion_status"] != "PUBLISHED":
        raise_err("ERR_DOCUMENT_NOT_PUBLISHED", "document %s is not published" % doc["id"])
    if doc["visibility_status"] != "PUBLIC":
        raise_err("ERR_DOCUMENT_SEALED", "document %s is not public" % doc["id"])


@bp.post("/legal-research/documents/<document_id>/headnotes")
@require_roles("AttorneyEditor")
def create_headnote(document_id):
    body = get_body()
    topic_code = req_enum(body, "topic_code", TOPIC_CODES)
    headnote_text = req_str(body, "headnote_text")
    synopsis_text = req_str(body, "synopsis_text")

    # Creation asks only that the target document exists (PRD 3.3).
    if document_id not in store.documents:
        raise_err("ERR_DOCUMENT_NOT_FOUND", "document %s does not exist" % document_id)

    headnote = stamp_new({
        "document_id": document_id,
        "author_editor_id": g.user_id,  # author identity comes from the header, never the body
        "reviewer_editor_id": None,
        "topic_code": topic_code,
        "headnote_text": headnote_text,
        "synopsis_text": synopsis_text,
        "review_note": None,
        "status": "DRAFT",
    })
    store.headnotes[headnote["id"]] = headnote
    return ok_object(serialize_headnote(headnote), 201)


@bp.get("/legal-research/headnotes")
@require_roles(*ANY_ROLE)
def list_headnotes():
    f_document = request.args.get("document_id")
    f_author = request.args.get("author_editor_id")
    f_status = opt_enum_query("status", HEADNOTE_STATUSES)

    rows = list(store.headnotes.values())
    if f_document is not None:
        rows = [h for h in rows if h["document_id"] == f_document]
    if f_author is not None:
        rows = [h for h in rows if h["author_editor_id"] == f_author]
    if f_status is not None:
        rows = [h for h in rows if h["status"] == f_status]
    return list_response(rows, serialize_headnote)


@bp.get("/legal-research/headnotes/<headnote_id>")
@require_roles(*ANY_ROLE)
def get_headnote(headnote_id):
    return ok_object(serialize_headnote(_get_headnote_or_404(headnote_id)))


@bp.post("/legal-research/headnotes/<headnote_id>/submit")
@require_roles("AttorneyEditor")
def submit_headnote(headnote_id):
    headnote = _get_headnote_or_404(headnote_id)

    # Ownership (priority 4): submission is personal to the author.
    if g.user_id != headnote["author_editor_id"]:
        raise_err("ERR_NOT_HEADNOTE_AUTHOR", "only the author may submit headnote %s" % headnote_id)

    if headnote["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "headnote %s is not in DRAFT" % headnote_id)
    _document_gates(headnote)

    headnote["status"] = "IN_REVIEW"
    touch(headnote)
    return ok_object(serialize_headnote(headnote), 200)


@bp.post("/legal-research/headnotes/<headnote_id>/decide")
@require_roles("AttorneyEditor")
def decide_headnote(headnote_id):
    body = get_body()
    decision = req_enum(body, "decision", ("APPROVE", "REJECT"))
    review_note = opt_str(body, "review_note")

    headnote = _get_headnote_or_404(headnote_id)

    # State and document gates precede the segregation-of-duties check
    # (cascade priorities 18, 19, 20 before 26).
    if headnote["status"] != "IN_REVIEW":
        raise_err("ERR_INVALID_STATE", "headnote %s is not in IN_REVIEW" % headnote_id)
    _document_gates(headnote)
    if g.user_id == headnote["author_editor_id"]:
        raise_err("ERR_REVIEWER_IS_AUTHOR", "reviewer must differ from the author")

    headnote["reviewer_editor_id"] = g.user_id
    headnote["review_note"] = review_note
    headnote["status"] = "PUBLISHED" if decision == "APPROVE" else "DRAFT"
    touch(headnote)
    return ok_object(serialize_headnote(headnote), 200)
