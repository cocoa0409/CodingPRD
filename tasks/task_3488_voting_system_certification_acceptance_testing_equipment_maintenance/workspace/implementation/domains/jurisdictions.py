"""Jurisdiction and budget-ledger endpoints (PRD 2.8, 3.1).

Ledger invariant: budget_total_cents == available_cents + encumbered_cents +
spent_cents at every observable instant. Adjustments move budget_total_cents
and available_cents by the signed delta and may not drive available negative.
"""
from flask import Blueprint

from auth import auth_context, require_role
from envelope import ok_object
from errors import err_not_found, raise_err
from store import db
from util import stamp_new, touch
from validation import body_json, no_extra, req_int, req_nonempty_str, req_state_code, req_str

bp = Blueprint("jurisdictions", __name__)


@bp.post("/evote/jurisdictions")
def create_jurisdiction():
    _, role = auth_context()
    require_role(role, {"PlatformAdmin"})
    body = body_json()
    no_extra(body, {"name", "state_code", "budget_total_cents"})
    total = req_int(body, "budget_total_cents", minv=0)
    rec = stamp_new({})
    rec.update({
        "name": req_str(body, "name"),
        "state_code": req_state_code(body, "state_code"),
        "budget_total_cents": total,
        "available_cents": total,
        "encumbered_cents": 0,
        "spent_cents": 0,
    })
    db.jurisdictions[rec["id"]] = rec
    return ok_object(rec, 201)


def get_jurisdiction_or_404(jurisdiction_id):
    jurisdiction = db.jurisdictions.get(jurisdiction_id)
    if jurisdiction is None:
        err_not_found("jurisdiction not found")
    return jurisdiction


@bp.get("/evote/jurisdictions/<jurisdiction_id>")
def get_jurisdiction(jurisdiction_id):
    auth_context()
    return ok_object(get_jurisdiction_or_404(jurisdiction_id), 200)


@bp.post("/evote/jurisdictions/<jurisdiction_id>/budget-adjustments")
def budget_adjustment(jurisdiction_id):
    _, role = auth_context()
    require_role(role, {"PlatformAdmin"})
    jurisdiction = get_jurisdiction_or_404(jurisdiction_id)
    body = body_json()
    no_extra(body, {"delta_cents", "reason"})
    delta = req_int(body, "delta_cents")
    req_nonempty_str(body, "reason")
    if jurisdiction["available_cents"] + delta < 0:
        raise_err("ERR_BUDGET_ADJUSTMENT_INVALID", 402, "adjustment would drive available_cents negative")
    jurisdiction["budget_total_cents"] += delta
    jurisdiction["available_cents"] += delta
    touch(jurisdiction)
    return ok_object(jurisdiction, 201)
