"""Researcher endpoints: register, read, tax documents, conduct actions."""
from flask import Blueprint

import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_FORBIDDEN,
)
from helpers import (
    base_entity, touch, get_body, require_fields, reject_unknown_fields,
)
from middleware import require_roles, check_researcher_owner
from response import success_object
from serializers import researcher_out
from services import cascades

bp = Blueprint("researchers", __name__)

CREATE_FIELDS = {"handle", "email", "country_code"}
TAX_FIELDS = {"document_type", "mark_verified"}
CONDUCT_FIELDS = {"action", "reason"}
CONDUCT_ACTIONS = {"WARNING", "STRIKE", "BAN", "REVERSE_LAST"}


def _get_researcher(rid):
    r = db.researchers.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, f"Researcher {rid} not found")
    return r


@bp.route("/api/researchers", methods=["POST"])
def register_researcher():
    require_roles({"Anonymous"})
    body = get_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    require_fields(body, ["handle", "email", "country_code"])
    for r in db.researchers.values():
        if r["handle"] == body["handle"]:
            raise_err(ERR_INVALID_REQUEST, "handle must be unique")
    r = base_entity()
    r.update(
        {
            "handle": body["handle"],
            "email": body["email"],
            "country_code": body["country_code"],
            "status": "ACTIVE",
            "strike_count": 0,
            "suspension_ends_at": None,
            "reputation_lifetime": 100,
            "reputation_rolling180": 100,
            "tier": "NOVICE",
            "tax_document_status": "MISSING",
            "tax_document_type": None,
            "conduct_log": [],
        }
    )
    db.researchers[r["id"]] = r
    return success_object(researcher_out(r), 201)


@bp.route("/api/researchers/<researcher_id>", methods=["GET"])
def read_researcher(researcher_id):
    require_roles({"PlatformAdmin", "ProgramAdmin", "Triager", "Researcher"})
    return success_object(researcher_out(_get_researcher(researcher_id)))


@bp.route("/api/researchers/<researcher_id>/tax-documents", methods=["POST"])
def tax_documents(researcher_id):
    user_id, role = require_roles({"Researcher", "PlatformAdmin"})
    r = _get_researcher(researcher_id)
    check_researcher_owner(user_id, role, researcher_id)
    body = get_body()
    reject_unknown_fields(body, TAX_FIELDS)
    mark_verified = body.get("mark_verified", False)
    if mark_verified:
        if role != "PlatformAdmin":
            raise_err(ERR_FORBIDDEN, "Only PlatformAdmin may mark tax documents verified")
        if r["tax_document_status"] == "MISSING":
            raise_err(ERR_INVALID_REQUEST, "No tax document submitted to verify")
        r["tax_document_status"] = "VERIFIED"
    else:
        doc_type = body.get("document_type")
        if not doc_type:
            raise_err(ERR_INVALID_REQUEST, "Missing required field: document_type")
        r["tax_document_status"] = "SUBMITTED"
        r["tax_document_type"] = doc_type
    touch(r)
    return success_object(researcher_out(r))


@bp.route("/api/researchers/<researcher_id>/conduct-actions", methods=["POST"])
def conduct_actions(researcher_id):
    require_roles({"ProgramAdmin", "Triager"})
    r = _get_researcher(researcher_id)
    body = get_body()
    reject_unknown_fields(body, CONDUCT_FIELDS)
    require_fields(body, ["action"])
    action = body["action"]
    if action not in CONDUCT_ACTIONS:
        raise_err(ERR_INVALID_REQUEST, "Invalid conduct action")
    cascades.apply_conduct_action(r, action, body.get("reason"))
    return success_object(researcher_out(r))
