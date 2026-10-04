"""ReverseOffsetRequest endpoints (PRD §3.8): state-initiated reverse matching
against federal debts, and confirmation with re-capped application."""
from datetime import timedelta

from flask import Blueprint

from constants import (
    REVERSE_REQUEST_TTL_DAYS,
    ROLE_STATE_COORDINATOR,
)
from db import STORE, clock_now, new_entity, touch
from errors import (
    err_invalid_state,
    err_no_reciprocal_agreement,
    err_not_found,
    err_request_expired,
)
from middleware import authenticate, get_body, require_roles, spec_field, validate_body
from response import ok
from serializers import serialize_reverse_request
from services.ledger import assess_remittance
from services.matching import agreement_covers, reverse_match
from util import gen_id

bp = Blueprint("reverse", __name__)


@bp.post("/reverse-offset-requests")
def create_reverse_request():
    ctx = authenticate()
    require_roles(ctx, ROLE_STATE_COORDINATOR)
    data = validate_body(get_body(), [
        spec_field("state_code", "str", required=True),
        spec_field("payee_tin", "str", required=True),
        spec_field("requested_amount_cents", "int", required=True, gt=0),
    ])
    # Coverage gate: ACTIVE agreement in the STATE_TO_FED scope at the clock.
    if not agreement_covers(data["state_code"], ("STATE_TO_FED", "BIDIRECTIONAL")):
        raise err_no_reciprocal_agreement()

    matches = reverse_match(data["payee_tin"], data["requested_amount_cents"])
    matched_total = sum(m["matched_amount_cents"] for m in matches)

    ent = new_entity()
    ent["id"] = gen_id()
    ent.update({
        "state_code": data["state_code"],
        "payee_tin": data["payee_tin"],
        "requested_amount_cents": data["requested_amount_cents"],
        "status": "MATCHED" if matches else "NO_MATCH",
        "matches": matches,
        "matched_total_cents": matched_total,
        # A matched request lives exactly ten days from creation.
        "expires_at": ent["created_at"] + timedelta(days=REVERSE_REQUEST_TTL_DAYS),
        "confirmed_at": None,
        "applied_total_cents": None,
    })
    STORE["reverse_requests"][ent["id"]] = ent
    return ok(serialize_reverse_request(ent), 201)


@bp.post("/reverse-offset-requests/<string:reverseOffsetRequestId>/confirm")
def confirm_reverse_request(reverseOffsetRequestId):
    """MATCHED -> CONFIRMED while the clock is on or before expires_at; a late
    confirm flips the request to EXPIRED and fails. Each match is re-capped to
    the debt's balance at confirmation time before application."""
    ctx = authenticate()
    require_roles(ctx, ROLE_STATE_COORDINATOR)
    validate_body(get_body(), [])
    req = STORE["reverse_requests"].get(reverseOffsetRequestId)
    if req is None:
        raise err_not_found("Reverse offset request not found")
    if req["status"] != "MATCHED":
        raise err_invalid_state("Only a MATCHED request can be confirmed")
    if clock_now() > req["expires_at"]:
        req["status"] = "EXPIRED"
        touch(req)
        raise err_request_expired()

    now = clock_now()
    applied_total = 0
    for match in req["matches"]:
        debt = STORE["debts"].get(match["debt_id"])
        if debt is None:
            continue
        amount = min(match["matched_amount_cents"], debt["current_balance_cents"])
        if amount <= 0:
            continue
        debt["current_balance_cents"] -= amount
        if debt["current_balance_cents"] == 0 and debt["status"] in ("ACTIVE", "IN_COLLECTION"):
            debt["status"] = "PAID_IN_FULL"
        touch(debt)
        creditor = STORE["creditors"].get(debt["creditor_agency_id"])
        if creditor is not None:
            assess_remittance(creditor, amount)
        applied_total += amount

    req["applied_total_cents"] = applied_total
    req["confirmed_at"] = now
    req["status"] = "CONFIRMED"
    touch(req)
    return ok(serialize_reverse_request(req))
