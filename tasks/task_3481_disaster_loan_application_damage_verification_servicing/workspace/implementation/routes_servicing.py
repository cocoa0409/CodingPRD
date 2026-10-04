"""Servicing actions (PRD 3.9): request, list, approve/deny with overlap rule."""

from flask import Blueprint, g, request

import calc
import clock
from auth import check_owner, require_roles
from body import json_body, req_dt, req_enum
from domain import bump, get_or_404, loan_actions, new_common
from envelope import page, parse_pagination, success, success_list
from errors import raise_err
from store import put
from serializers import serialize, serialize_all
from sweep import _activate_action

bp = Blueprint("servicing_actions", __name__)

ACTION_TYPES = {"DEFERMENT", "HARDSHIP"}


@bp.post("/disaster-relief/loans/<loan_id>/servicing-actions")
@require_roles("Applicant")
def request_action(loan_id):
    loan = get_or_404("loans", loan_id)
    check_owner(loan["applicant_id"])
    if loan["lifecycle_status"] != "ACTIVE":
        raise_err("ERR_LOAN_NOT_ACTIVE")
    data = json_body()
    action_type = req_enum(data, "action_type", ACTION_TYPES)
    start = req_dt(data, "start_date")
    end = req_dt(data, "end_date")
    if end <= start:
        raise_err("ERR_INVALID_REQUEST", "end_date must be strictly after start_date")
    if (end - start).days > calc.ACCOMMODATION_MAX_DAYS:
        raise_err("ERR_INVALID_REQUEST", "accommodation window may not exceed 360 days")
    row = new_common()
    row.update({
        "loan_id": loan["id"],
        "action_type": action_type,
        "start_date": start,
        "end_date": end,
        "status": "REQUESTED",
        "decided_by": None,
    })
    put("servicing_actions", row)
    return success(serialize(row), 201)


@bp.get("/disaster-relief/loans/<loan_id>/servicing-actions")
@require_roles("Applicant", "ServicingAgent")
def list_actions(loan_id):
    loan = get_or_404("loans", loan_id)
    check_owner(loan["applicant_id"])
    rows = loan_actions(loan["id"])
    limit, offset = parse_pagination(request.args)
    items, total = page(rows, limit, offset)
    return success_list(serialize_all(items), limit, offset, total)


@bp.post("/disaster-relief/servicing-actions/<action_id>/decision")
@require_roles("ServicingAgent")
def decide_action(action_id):
    action = get_or_404("servicing_actions", action_id)
    data = json_body()
    decision = req_enum(data, "decision", {"APPROVED", "DENIED"})
    if action["status"] != "REQUESTED":
        raise_err("ERR_ACTION_NOT_REQUESTED")
    loan = get_or_404("loans", action["loan_id"])
    if loan["lifecycle_status"] != "ACTIVE":
        raise_err("ERR_LOAN_NOT_ACTIVE")
    if decision == "DENIED":
        action["decided_by"] = g.user_id
        action["status"] = "DENIED"
        bump(action)
        return success(serialize(action))
    # APPROVED: half-open overlap check (adjacency allowed) precedes the DEFAULT gate.
    for other in loan_actions(loan["id"]):
        if other["id"] == action["id"] or other["status"] not in ("APPROVED", "ACTIVE"):
            continue
        if action["start_date"] < other["end_date"] and action["end_date"] > other["start_date"]:
            raise_err("ERR_ACCOMMODATION_OVERLAP")
    if loan["servicing_status"] == "DEFAULT":
        raise_err("ERR_ACCOMMODATION_NOT_ALLOWED")
    action["decided_by"] = g.user_id
    action["status"] = "APPROVED"
    bump(action)
    # If the window has already started, the action activates immediately in this request.
    if action["start_date"] <= clock.get_current() and loan["servicing_status"] == "CURRENT":
        _activate_action(action, loan)
    return success(serialize(action))
