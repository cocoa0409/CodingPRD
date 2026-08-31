"""Literary properties, chain-of-title documents and the logical clock."""

from flask import Blueprint

import calc
from core import (
    Field, authenticate, collection_rows, created, db, fail, filter_eq, fmt_dt,
    json_body, lookup, new_row, ok, ok_list, paginate, pagination, parse_date,
    parse_dt, parse_fields, qp, touch,
)

bp = Blueprint("property", __name__)

READ_PROPERTY_ROLES = ("SlateAdmin", "StoryEditor", "BusinessAffairs", "DevelopmentExec",
                       "Reader", "CommitteeMember")
DOC_LIST_ROLES = ("SlateAdmin", "StoryEditor", "BusinessAffairs", "DevelopmentExec")
DOC_READ_ROLES = ("SlateAdmin", "StoryEditor", "BusinessAffairs")


@bp.post("/literary-properties")
def create_property():
    authenticate(("StoryEditor", "SlateAdmin"))
    body = json_body()
    data = parse_fields(body, [
        Field("title", "string", required=True),
        Field("material_type", "enum", required=True, enum=calc.MATERIAL_TYPES),
        Field("source_author_name", "string", required=True),
        Field("genre", "enum", required=True, enum=calc.GENRES),
        Field("logline", "string", default=""),
    ])
    row = new_row("properties", {
        "title": data["title"],
        "material_type": data["material_type"],
        "source_author_name": data["source_author_name"],
        "genre": data["genre"],
        "logline": data["logline"],
        "rights_chain_status": "UNVERIFIED",
        "verified_document_count": 0,
        "tracking_tier": "NONE",
        "encumbrance_count": 0,
    })
    return created(row)


@bp.get("/literary-properties/<pid>")
def read_property(pid):
    authenticate(READ_PROPERTY_ROLES)
    return ok(lookup("properties", pid, "ERR_PROPERTY_NOT_FOUND"))


@bp.get("/literary-properties")
def list_properties():
    authenticate(READ_PROPERTY_ROLES)
    limit, offset = pagination()
    rows = collection_rows("properties")
    rows = filter_eq(rows, "tracking_tier", qp("tracking_tier"))
    rows = filter_eq(rows, "rights_chain_status", qp("rights_chain_status"))
    rows = filter_eq(rows, "genre", qp("genre"))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/literary-properties/<pid>/rights-documents")
def file_document(pid):
    authenticate(("BusinessAffairs",))
    prop = lookup("properties", pid, "ERR_PROPERTY_NOT_FOUND")
    body = json_body()
    predecessor = None
    if body.get("supersedes_document_id") is not None:
        predecessor = lookup("documents", body.get("supersedes_document_id"),
                             "ERR_DOCUMENT_NOT_FOUND")
    data = parse_fields(body, [
        Field("doc_type", "enum", required=True, enum=calc.DOC_TYPES),
        Field("executed_on", "date", required=True),
        Field("verified", "boolean", required=True),
        Field("supersedes_document_id", "string"),
        Field("notes", "string", default=""),
    ])
    parse_date(data["executed_on"])
    row = new_row("documents", {
        "property_id": prop["id"],
        "doc_type": data["doc_type"],
        "executed_on": data["executed_on"],
        "verified": data["verified"],
        "supersedes_document_id": data["supersedes_document_id"],
        "notes": data["notes"],
        "superseded": False,
    }, versioned=False)
    if predecessor is not None:
        predecessor["superseded"] = True
    calc.recompute_rights_chain(prop)
    touch(prop)
    return created(row)


@bp.get("/literary-properties/<pid>/rights-documents")
def list_property_documents(pid):
    authenticate(DOC_LIST_ROLES)
    prop = lookup("properties", pid, "ERR_PROPERTY_NOT_FOUND")
    limit, offset = pagination()
    rows = calc.documents_of(prop["id"])
    rows = filter_eq(rows, "doc_type", qp("doc_type"))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/rights-chain-documents/<did>")
def read_document(did):
    authenticate(DOC_READ_ROLES)
    return ok(lookup("documents", did, "ERR_DOCUMENT_NOT_FOUND"))


@bp.get("/rights-chain-documents")
def list_documents():
    authenticate(DOC_READ_ROLES)
    limit, offset = pagination()
    rows = collection_rows("documents")
    rows = filter_eq(rows, "property_id", qp("property_id"))
    rows = filter_eq(rows, "supersedes_document_id", qp("supersedes_document_id"))
    rows = filter_eq(rows, "doc_type", qp("doc_type"))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("SlateAdmin",))
    body = json_body()
    data = parse_fields(body, [Field("to_iso8601", "string", required=True)])
    parsed = parse_dt(data["to_iso8601"])
    db.clock_dt = parsed
    db.clock_raw = data["to_iso8601"]
    return ok({"current_utc": db.clock_raw})


@bp.get("/_clock")
def read_clock():
    authenticate(("SlateAdmin", "StoryEditor", "BusinessAffairs", "DevelopmentExec"))
    return ok({"current_utc": db.clock_raw})
