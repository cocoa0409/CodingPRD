"""Logical-clock and payment-simulation test-driving endpoints (PRD 2.10)."""

from flask import Blueprint

from db import DB
from errors import fail
from repository import get, serialize
from response import object_response
from routes.common import body, instant_field, text_field
from services import ledger, sweeps

bp = Blueprint("ops", __name__)

OUTCOMES = ("SUCCEEDED", "REFUNDED")


@bp.post("/_clock/set_current_utc")
def set_clock():
    payload = body()
    instant = instant_field(payload, "current_utc")
    if instant < DB.now:
        fail("ERR_INVALID_REQUEST", "The logical clock does not run backwards.")
    # The contract surfaces instants at millisecond resolution, and sub-millisecond
    # precision is never observable in any response. Normalising the clock here
    # keeps every derived stamp on the same grid, so two rows written in the same
    # logical instant share a created_at value rather than differing invisibly.
    DB.now = instant.replace(microsecond=(instant.microsecond // 1000) * 1000)
    sweeps.run_all()
    return object_response({})


@bp.post("/_payments/simulate")
def simulate_payment():
    payload = body()
    order = get("order", text_field(payload, "order_id"))
    outcome = text_field(payload, "outcome")
    if outcome not in OUTCOMES:
        fail("ERR_INVALID_REQUEST", "outcome must be SUCCEEDED or REFUNDED.")
    amount = order["order_fee_cents"] if outcome == "SUCCEEDED" else -order["order_fee_cents"]
    entry_type = "ORDER_FEE_PAYMENT" if outcome == "SUCCEEDED" else "ORDER_FEE_REFUND"
    ledger.write_entry(order["id"], entry_type, amount, "PAYMENT_SIMULATION_" + outcome)
    return object_response(serialize(order), 201)