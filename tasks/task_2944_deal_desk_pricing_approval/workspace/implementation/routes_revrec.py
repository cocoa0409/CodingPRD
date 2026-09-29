"""Revenue recognition assessments (PRD 3.6)."""
from flask import Blueprint

import auth
import calc
import clock
import common
import db
import response
import validation
from auth import require_roles
from errors import fail
from validation import validate, json_body

bp = Blueprint("revrec", __name__)

ALL = auth.ALL_ROLES

ASSESSMENT_SPEC = {"quote_id": {"type": "string", "required": True}}


def _allocation_for(quote):
    return calc.allocate(quote, db.lines_of_quote(quote["id"]))


@bp.post("/revrec-assessments")
@require_roles("RevenueAccountant", "DealDeskAnalyst")
def create_revrec_assessment():
    body = validate(json_body(), ASSESSMENT_SPEC)
    quote = db.quote(body["quote_id"])
    if quote is None:
        fail("ERR_QUOTE_NOT_FOUND")
    allocation = _allocation_for(quote)
    record = {
        "quote_id": quote["id"],
        "arrangement_type": allocation["arrangement_type"],
        "status": "ASSESSED",
        "allocable_amount_cents": allocation["allocable_amount_cents"],
        "usage_excluded_cents": allocation["usage_excluded_cents"],
        "allocation_residual_cents": allocation["allocation_residual_cents"],
        "allocation_lines": allocation["allocation_lines"],
        "snapshot_quote_version": quote["version"],
        "assessed_by_user_id": None,
        "assessed_at": None,
        "assessment_note": None,
    }
    db.insert("revrec_assessments", record)
    return response.created(record)


@bp.get("/quotes/<quote_id>/revrec-assessments")
@require_roles(ALL)
def list_quote_assessments(quote_id):
    common.must_get("quotes", quote_id)
    window, total, limit, offset = validation.paginate(db.assessments_of_quote(quote_id))
    return response.listing(window, total, limit, offset)


ASSESS_SPEC = {
    "decision": {"type": "enum", "required": True, "values": ("CLEAR", "BLOCK")},
    "assessment_note": {"type": "string"},
}


@bp.post("/revrec-assessments/<assessment_id>/assess")
@require_roles("RevenueAccountant")
def assess_revrec_assessment(assessment_id):
    row = common.must_get("revrec_assessments", assessment_id)
    body = validate(json_body(), ASSESS_SPEC)
    quote = db.quote(row["quote_id"])

    if row["status"] not in ("ASSESSED", "STALE"):
        fail("ERR_REVREC_STATE_INVALID")
    if quote["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        fail("ERR_QUOTE_NOT_DRAFT")

    if body["decision"] == "CLEAR":
        allocation = _allocation_for(quote)
        row["arrangement_type"] = allocation["arrangement_type"]
        row["allocable_amount_cents"] = allocation["allocable_amount_cents"]
        row["usage_excluded_cents"] = allocation["usage_excluded_cents"]
        row["allocation_lines"] = allocation["allocation_lines"]
        row["allocation_residual_cents"] = allocation["allocation_residual_cents"]
        row["status"] = "CLEARED"
        row["snapshot_quote_version"] = quote["version"]
    else:
        row["status"] = "BLOCKED"
    row["assessed_by_user_id"] = auth.current_user_id()
    row["assessed_at"] = clock.now()
    row["assessment_note"] = body.get("assessment_note")
    db.touch(row)
    return response.ok(row)
