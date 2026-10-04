"""Market conduct data calls, responses, and cost allocation (PRD 3.7)."""

from flask import Blueprint

import calc
from auth import (
    authenticate,
    require_role,
    forbidden,
    ALL_ROLES,
    ROLE_STATE_REGULATOR,
    ROLE_INSURER_USER,
)
from db import store, base_record, touch
from errors import ApiError
from serialize import serialize_call, serialize_response
from util import get_body, req_str, req_int, ok_object, paginate

bp = Blueprint("market_conduct", __name__)


def get_call_or_404(call_id):
    c = store.calls.get(call_id)
    if c is None:
        raise ApiError(
            "ERR_MARKET_CONDUCT_CALL_NOT_FOUND",
            "Market conduct call not found: %s" % call_id,
            404,
        )
    return c


@bp.post("/naic/market-conduct-calls")
def create_call():
    principal = authenticate()
    require_role(principal, {ROLE_STATE_REGULATOR})
    body = get_body()
    call_code = req_str(body, "call_code")
    topic = req_str(body, "topic")
    total_cost_cents = req_int(body, "total_cost_cents", minimum=0)
    for c in store.calls.values():
        if c["call_code"] == call_code:
            raise ApiError(
                "ERR_DUPLICATE_CALL_CODE",
                "Market conduct call code already exists: %s" % call_code,
                409,
            )
    if total_cost_cents < calc.MIN_CALL_COST_CENTS:
        raise ApiError(
            "ERR_CALL_COST_BELOW_MINIMUM",
            "total_cost_cents must be at least %d" % calc.MIN_CALL_COST_CENTS,
            422,
        )
    rec = base_record()
    rec.update({
        "call_code": call_code,
        "topic": topic,
        # Derived from the acting regulator's state; never client-supplied.
        "lead_state_code": principal.entity["code"],
        "total_cost_cents": total_cost_cents,
        "status": "OPEN",
    })
    store.calls[rec["id"]] = rec
    return ok_object(serialize_call(rec), 201)


@bp.get("/naic/market-conduct-calls/<call_id>")
def read_call(call_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    return ok_object(serialize_call(get_call_or_404(call_id)), 200)


@bp.post("/naic/market-conduct-calls/<call_id>/responses")
def create_response(call_id):
    principal = authenticate()
    require_role(principal, {ROLE_INSURER_USER})
    call = get_call_or_404(call_id)
    body = get_body()
    premium = req_int(body, "direct_premium_cents")
    if premium <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", "direct_premium_cents must be strictly positive", 400
        )
    complaints = req_int(body, "complaint_count", minimum=0)
    # State gate evaluated before the duplicate check (PRD 3.7).
    if call["status"] != "OPEN":
        raise ApiError(
            "ERR_CALL_NOT_OPEN", "Call %s is not OPEN" % call_id, 409
        )
    insurer = principal.entity
    for r in store.responses.values():
        if r["call_id"] == call_id and r["insurer_naic_code"] == insurer["naic_code"]:
            raise ApiError(
                "ERR_DUPLICATE_RESPONSE",
                "Insurer %s already responded to this call" % insurer["naic_code"],
                409,
            )
    total_premium_incl_self = premium + sum(
        r["direct_premium_cents"]
        for r in store.responses.values()
        if r["call_id"] == call_id
    )
    rec = base_record()
    rec.update({
        "call_id": call_id,
        "insurer_naic_code": insurer["naic_code"],
        "direct_premium_cents": premium,
        "complaint_count": complaints,
        "exam_priority_score": calc.exam_priority_score(
            premium, complaints, insurer, total_premium_incl_self
        ),
        "escalation_flag": insurer["status"] == "UNDER_SUPERVISION",
        "allocated_cost_cents": None,
        "cost_share_excluded": None,
    })
    store.responses[rec["id"]] = rec
    return ok_object(serialize_response(rec), 201)


@bp.get("/naic/market-conduct-calls/<call_id>/responses")
def list_responses(call_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    call = get_call_or_404(call_id)
    rsps = [r for r in store.responses.values() if r["call_id"] == call["id"]]
    return paginate(rsps, serialize_response)


@bp.post("/naic/market-conduct-calls/<call_id>/close")
def close_call(call_id):
    principal = authenticate()
    require_role(principal, {ROLE_STATE_REGULATOR})
    call = get_call_or_404(call_id)
    if principal.entity["code"] != call["lead_state_code"]:
        forbidden("Only a regulator of the lead state may close this call")
    if call["status"] != "OPEN":
        raise ApiError("ERR_CALL_NOT_OPEN", "Call %s is not OPEN" % call_id, 409)
    responses = [r for r in store.responses.values() if r["call_id"] == call_id]
    if not responses:
        raise ApiError(
            "ERR_CALL_NO_RESPONSES",
            "Cannot close a call with zero responses",
            422,
        )
    allocation = calc.cost_share_allocation(call["total_cost_cents"], responses)
    for r in responses:
        allocated, excluded = allocation[r["id"]]
        r["allocated_cost_cents"] = allocated
        r["cost_share_excluded"] = excluded
        touch(r)
    call["status"] = "CLOSED"
    touch(call)
    return ok_object(serialize_call(call), 200)
