"""Billing charges: reads and the money state machine (PRD §3.7)."""
from flask import Blueprint

import serialize
from core import (
    ADMIN, READ_ROLES, authenticate, body, db, fail, lookup, ok, ordered,
    paginate, qfilter, touch,
)
from ladder import assert_transition, assert_version, require_action, require_version_field

bp = Blueprint("billing", __name__)

CHARGE_TRANSITIONS = {
    "INVOICE": ("PENDING",),
    "PAY": ("PENDING", "INVOICED"),
    "WAIVE": ("PENDING", "INVOICED"),
    "VOID": ("PENDING", "INVOICED"),
}
TERMINAL_CHARGE_STATES = ("PAID", "WAIVED", "VOID")


@bp.get("/billing-charges/<charge_id>")
def read_charge(charge_id):
    authenticate(READ_ROLES)
    return ok(serialize.charge(lookup("charges", charge_id)))


@bp.get("/billing-charges")
def list_charges():
    authenticate(READ_ROLES)
    rows = ordered(db.charges)
    rows = qfilter(rows, "member_id")
    rows = qfilter(rows, "lockbox_id")
    rows = qfilter(rows, "placement_id")
    rows = qfilter(rows, "charge_type")
    rows = qfilter(rows, "status")
    return paginate(rows, serialize.charge)


@bp.post("/billing-charges/<charge_id>/state")
def charge_state(charge_id):
    authenticate([ADMIN])
    charge = lookup("charges", charge_id)
    payload = body()

    action = require_action(payload, tuple(CHARGE_TRANSITIONS))
    expected = require_version_field(payload, "expected_charge_version")

    assert_version(expected, charge)

    # PRD §3.7 — any money action on a settled charge is ERR_CHARGE_NOT_ADJUSTABLE.
    if charge["status"] in TERMINAL_CHARGE_STATES:
        fail("ERR_CHARGE_NOT_ADJUSTABLE", "The charge has already been settled.")
    assert_transition(charge["status"], CHARGE_TRANSITIONS, action)

    if action == "VOID" and charge["charge_type"] == "REPLACEMENT":
        lockbox = db.lockboxes.get(charge.get("lockbox_id"))
        if lockbox is not None and lockbox["status"] == "RETIRED":
            fail("ERR_CHARGE_NOT_ADJUSTABLE",
                 "A replacement charge for a retired lockbox may not be voided.")

    placement = db.placements.get(charge.get("placement_id")) if charge.get("placement_id") else None

    if action == "INVOICE":
        charge["status"] = "INVOICED"
    elif action in ("PAY", "WAIVE"):
        charge["status"] = "PAID" if action == "PAY" else "WAIVED"
        if placement is not None and placement["billing_status"] == "ACCRUED":
            placement["billing_status"] = "SETTLED"
            touch(placement)
    elif action == "VOID":
        charge["status"] = "VOID"
        if placement is not None and placement["billing_status"] == "ACCRUED":
            placement["billing_status"] = "NONE"
            touch(placement)

    touch(charge)
    return ok(serialize.charge(charge))
