"""Refund claims and the segregation-of-duties decision — PRD 3.9."""

from flask import Blueprint

import serialize
import validation as v
from auth import require
from envelope import ok, ok_list, read_pagination, paginate, enum_param, str_param
from errors import ApiError
from store import store

bp = Blueprint("claims", __name__)

CLAIM_STATUSES = ("OPEN", "APPROVED", "DENIED", "PAID")


def find_claim(claim_id):
    row = store.claims.get(claim_id)
    if row is None:
        raise ApiError("ERR_REFUND_CLAIM_NOT_FOUND", "No refund claim with id %s." % claim_id)
    return row


@bp.get("/harbor/refund-claims/<claim_id>")
def read_claim(claim_id):
    require("FareAuditor", "Dispatcher", "HarborAdmin", "Rider")
    return ok(serialize.refund_claim(find_claim(claim_id)))


@bp.get("/harbor/refund-claims")
def list_claims():
    require("FareAuditor", "Dispatcher", "HarborAdmin", "Rider")
    limit, offset = read_pagination()
    booking_id = str_param("booking_id")
    interruption_id = str_param("service_interruption_id")
    status = enum_param("status", CLAIM_STATUSES)
    rows = []
    for claim in store.claims.values():
        if booking_id is not None and claim["booking_id"] != booking_id:
            continue
        if interruption_id is not None and claim["service_interruption_id"] != interruption_id:
            continue
        if status is not None and claim["status"] != status:
            continue
        rows.append(claim)
    rows = store.ordered(rows)
    window = paginate(rows, limit, offset)
    return ok_list([serialize.refund_claim(r) for r in window], limit, offset, len(rows))


@bp.post("/harbor/refund-claims/<claim_id>/approve")
def decide_claim(claim_id):
    actor = require("FareAuditor")
    claim = find_claim(claim_id)
    body = v.body()

    # rung 6 — payload validity
    decision = v.get_enum(body, "decision", ("APPROVE", "DENY"))

    # rung 10 — state precondition
    if claim["status"] != "OPEN":
        raise ApiError("ERR_REFUND_CLAIM_NOT_OPEN", "The refund claim is not OPEN.")

    # rung 23 — segregation of duties
    if actor.user_id == claim["declarer_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The declaring user may not decide this claim.")

    if decision == "APPROVE":
        claim["status"] = "APPROVED"
        claim["approver_user_id"] = actor.user_id
        booking = store.bookings.get(claim["booking_id"])
        if booking is not None:
            booking["fare_refunded_cents"] = claim["cash_refund_cents"]
            booking["credit_refunded_cents"] = claim["credit_refund_cents"]
            store.touch(booking)
        store.touch(claim)
        # disbursement completes inside the same request
        claim["status"] = "PAID"
        store.touch(claim)
    else:
        claim["status"] = "DENIED"
        claim["approver_user_id"] = actor.user_id
        store.touch(claim)

    _bubble_interruption(claim["service_interruption_id"])
    return ok(serialize.refund_claim(claim))


def _bubble_interruption(interruption_id):
    interruption = store.interruptions.get(interruption_id)
    if interruption is None or interruption["status"] != "DECLARED":
        return
    siblings = [c for c in store.claims.values()
                if c["service_interruption_id"] == interruption_id]
    if not siblings:
        return
    if any(c["status"] == "OPEN" for c in siblings):
        return
    interruption["status"] = "RESOLVED"
    store.touch(interruption)
