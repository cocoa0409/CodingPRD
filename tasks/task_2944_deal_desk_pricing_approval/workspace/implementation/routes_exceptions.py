"""Competitive pricing exceptions (PRD 3.5, 2.12)."""
from flask import Blueprint

import auth
import calc
import clock
import common
import db
import response
import validation
import workflow
from auth import require_roles
from errors import fail
from validation import validate, json_body

bp = Blueprint("exceptions", __name__)

ALL = auth.ALL_ROLES

EXCEPTION_SPEC = {
    "quote_id": {"type": "string", "required": True},
    "competitor_name": {"type": "string", "required": True},
    "competitor_quoted_total_cents": {"type": "integer", "required": True, "gt": 0},
    "evidence_reference": {"type": "string", "required": True},
    "justification": {"type": "string", "required": True},
}


@bp.post("/competitive-exceptions")
@require_roles("SalesRep")
def create_competitive_exception():
    body = validate(json_body(), EXCEPTION_SPEC)
    quote = db.quote(body["quote_id"])
    if quote is None:
        fail("ERR_QUOTE_NOT_FOUND")
    common.require_owner(quote)
    record = {
        "quote_id": quote["id"],
        "competitor_name": body["competitor_name"],
        "competitor_quoted_total_cents": body["competitor_quoted_total_cents"],
        "evidence_reference": body["evidence_reference"],
        "justification": body["justification"],
        "documented_by_user_id": auth.current_user_id(),
        "status": "SUBMITTED",
        "allowance_consumed_cents": 0,
        "decided_by_user_id": None,
        "decided_at": None,
        "decision_note": None,
        "released_at": None,
    }
    db.insert("competitive_exceptions", record)
    return response.created(record)


@bp.get("/quotes/<quote_id>/competitive-exceptions")
@require_roles(ALL)
def list_quote_exceptions(quote_id):
    common.must_get("quotes", quote_id)
    window, total, limit, offset = validation.paginate(db.exceptions_of_quote(quote_id))
    return response.listing(window, total, limit, offset)


DECIDE_SPEC = {
    "decision": {"type": "enum", "required": True, "values": ("ACCEPT", "REJECT")},
    "decision_note": {"type": "string"},
}


@bp.post("/competitive-exceptions/<exception_id>/decide")
@require_roles("DealDeskAnalyst", "CFO")
def decide_competitive_exception(exception_id):
    row = common.must_get("competitive_exceptions", exception_id)
    body = validate(json_body(), DECIDE_SPEC)
    quote = db.quote(row["quote_id"])
    policy = common.policy_of(quote)

    if row["status"] != "SUBMITTED":
        fail("ERR_EXCEPTION_STATE_INVALID")
    if quote["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        fail("ERR_QUOTE_NOT_DRAFT")
    if auth.current_user_id() == row["documented_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The author of an exception may not decide it.")

    if body["decision"] == "REJECT":
        row["status"] = "REJECTED"
        row["decided_by_user_id"] = auth.current_user_id()
        row["decided_at"] = clock.now()
        row["decision_note"] = body.get("decision_note")
        db.touch(row)
        return response.ok(row)

    margin = calc.dec(quote["final_margin_pct"])
    if not margin < calc.dec(policy["margin_floor_pct"]):
        fail(
            "ERR_EXCEPTION_NOT_NEEDED",
            "final_margin_pct is at or above the policy's margin_floor_pct.",
        )
    if margin < calc.dec(policy["absolute_margin_floor_pct"]):
        fail("ERR_ABSOLUTE_MARGIN_FLOOR_BREACH")

    give_up = calc.margin_give_up_cents(policy, margin, quote["final_net_total_cents"])
    account = db.account(quote["account_id"])
    used = int(account["exception_allowance_used_cents"])
    if used + give_up > int(policy["exception_allowance_cents"]):
        fail("ERR_EXCEPTION_ALLOWANCE_EXHAUSTED")

    row["status"] = "ACCEPTED"
    row["decided_by_user_id"] = auth.current_user_id()
    row["decided_at"] = clock.now()
    row["decision_note"] = body.get("decision_note")
    row["allowance_consumed_cents"] = give_up
    db.touch(row)

    account["exception_allowance_used_cents"] = used + give_up
    db.touch(account)

    workflow.reprice(quote, policy)
    db.touch(quote)
    workflow.stale_assessments(quote)
    return response.ok(row)


REVOKE_SPEC = {"decision_note": {"type": "string"}}


@bp.post("/competitive-exceptions/<exception_id>/revoke")
@require_roles("CFO")
def revoke_competitive_exception(exception_id):
    row = common.must_get("competitive_exceptions", exception_id)
    body = validate(json_body(), REVOKE_SPEC)
    quote = db.quote(row["quote_id"])

    if row["status"] != "ACCEPTED":
        fail("ERR_EXCEPTION_STATE_INVALID")
    if quote["status"] not in ("DRAFT", "CHANGES_REQUESTED", "PENDING_APPROVAL"):
        fail("ERR_QUOTE_STATE_INVALID_FOR_REVOKE")

    row["status"] = "REVOKED"
    row["released_at"] = clock.now()
    if "decision_note" in body:
        row["decision_note"] = body["decision_note"]
    db.touch(row)

    account = db.account(quote["account_id"])
    account["exception_allowance_used_cents"] = (
        int(account["exception_allowance_used_cents"]) - int(row["allowance_consumed_cents"])
    )
    db.touch(account)

    workflow.recompute_approval_level(quote, common.policy_of(quote))
    db.touch(quote)
    workflow.stale_assessments(quote)
    return response.ok(row)
