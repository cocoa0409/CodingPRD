"""SafetyInspection — the derived verdict and its three disjoint cascades
(PRD §3.7)."""

from decimal import Decimal

from flask import Blueprint, request

from db import db, new_row, now_iso, public, touch
from errors import ApiError
from middleware import EP, SO, VOM, caller_id, roles
from response import list_response, object_response
from routes.orders import move_to_refund_due
from services import calc, derive
from services.validate import Body, fail

bp = Blueprint("inspections", __name__)

INSPECTION_TYPES = ("EGRESS", "CAPACITY", "ACCESSIBILITY", "SENSORY")
SEVERITIES = ("NONE", "MINOR", "MAJOR", "CRITICAL")
SUSPENDABLE_SLOTS = ("OPEN", "SOLD_OUT")


@bp.post("/safety-inspections")
@roles(SO)
def book_inspection():
    body = Body(require_body=True)
    run_id = body.reference("run_id")
    inspection_type = body.enum("inspection_type", INSPECTION_TYPES)
    scheduled_for, scheduled_raw = body.instant_field("scheduled_for_utc")

    # rung 5 — body foreign key
    run_row = derive.run(run_id)
    # rung 9 — a closed run is no longer inspectable
    if run_row["run_status"] == "CLOSED":
        raise ApiError("ERR_RUN_INVALID_STATE")

    row = new_row()
    row.update({
        "run_id": run_row["id"],
        "inspection_type": inspection_type,
        "scheduled_for_utc": scheduled_raw,
        "measured_egress_width_cm": 0,
        "findings_count": 0,
        "severity": "NONE",
        "outcome": None,
        "findings_note": None,
        "allowed_occupancy_cap": 0,
        "finalized_by_user_id": None,
        "finalized_at": None,
        "status": "SCHEDULED",
        "_scheduled_for": scheduled_for,
    })
    db.inspections[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/safety-inspections/<inspection_id>")
@roles(SO, EP, VOM)
def read_inspection(inspection_id):
    return object_response(public(derive.inspection(inspection_id)))


@bp.get("/safety-inspections")
@roles(SO, EP, VOM)
def list_inspections():
    rows = list(db.inspections.values())
    for field in ("run_id", "inspection_type", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return list_response(rows)


def _cascade_conditional(run_row, inspection_row):
    """The authority caps the room rather than closing it."""
    cap = inspection_row["allowed_occupancy_cap"]
    run_row["effective_capacity_cap"] = cap
    # a roomless run must not raise here: the cascade is not a capacity request
    derive.refresh_effective_capacity(run_row, tolerate_empty=True)
    touch(run_row)
    for slot_row in derive.slots_of(run_row):
        if (slot_row["status"] in SUSPENDABLE_SLOTS
                and slot_row["base_capacity"] > cap):
            slot_row["status"] = "SUSPENDED"
            touch(slot_row)


def _cascade_fail(run_row, inspection_row):
    """Four causal hops: verdict, run suspension, slot suspension, refunds."""
    # hop 2
    run_row["clearance_status"] = "SUSPENDED"
    run_row["suspended_at"] = now_iso()
    run_row["suspending_inspection_id"] = inspection_row["id"]
    touch(run_row)

    suspended = []
    for slot_row in derive.slots_of(run_row):
        if slot_row["status"] in SUSPENDABLE_SLOTS:
            # hop 3 — the seat counters are deliberately preserved
            slot_row["status"] = "SUSPENDED"
            touch(slot_row)
            suspended.append(slot_row)

    for slot_row in suspended:
        for order_row in derive.orders_of_slot(slot_row):
            if order_row["status"] == "CONFIRMED":
                # hop 4 — operator fault: the whole collection goes back and
                # nothing is retained as credit
                move_to_refund_due(order_row, Decimal("1.00"))


@bp.post("/safety-inspections/<inspection_id>/finalize")
@roles(SO)
def finalize_inspection(inspection_id):
    inspection_row = derive.inspection(inspection_id)
    body = Body(require_body=True)
    measured = body.number("measured_egress_width_cm", minimum=0)
    severity = body.enum("severity", SEVERITIES)
    findings_count = body.integer("findings_count", required=False, default=0,
                                  minimum=0, maximum=200)
    note = body.string("findings_note", required=False, default=None, min_len=1,
                       max_len=500)

    # rung 8 — own state
    if inspection_row["status"] != "SCHEDULED":
        raise ApiError("ERR_INSPECTION_INVALID_STATE")

    run_row = derive.run(inspection_row["run_id"])
    venue_row = derive.venue(run_row["venue_id"])

    # rung 14 — a clean severity cannot carry findings
    if severity == "NONE" and findings_count > 0:
        raise ApiError("ERR_SEVERITY_FINDINGS_MISMATCH")

    outcome = calc.inspection_outcome(inspection_row["inspection_type"], severity,
                                      findings_count, measured,
                                      venue_row["egress_width_cm"])
    # the narrative is conditionally mandatory on the DERIVED verdict
    if outcome != "PASS" and note is None:
        fail("Field 'findings_note' is required when the derived outcome is not "
             "PASS.")

    # hop 1 — the inspection's own verdict fields, on every branch
    inspection_row["measured_egress_width_cm"] = float(calc.two_dp(measured))
    inspection_row["severity"] = severity
    inspection_row["findings_count"] = findings_count
    inspection_row["findings_note"] = note
    inspection_row["outcome"] = outcome
    inspection_row["allowed_occupancy_cap"] = calc.allowed_occupancy_cap(measured)
    inspection_row["finalized_by_user_id"] = caller_id()
    inspection_row["finalized_at"] = now_iso()
    inspection_row["_finalized_at"] = inspection_row["finalized_at"]
    inspection_row["status"] = "FINALIZED"
    touch(inspection_row)

    if outcome == "CONDITIONAL":
        _cascade_conditional(run_row, inspection_row)
    elif outcome == "FAIL":
        _cascade_fail(run_row, inspection_row)
    # on PASS nothing outside the inspection row changes at all
    return object_response(public(inspection_row))


@bp.post("/safety-inspections/<inspection_id>/void")
@roles(SO)
def void_inspection(inspection_id):
    inspection_row = derive.inspection(inspection_id)
    body = Body()
    note = body.string("note", required=False, default=None, min_len=1,
                       max_len=500)

    # rung 8 — own state
    if inspection_row["status"] != "SCHEDULED":
        raise ApiError("ERR_INSPECTION_INVALID_STATE")

    inspection_row["status"] = "VOIDED"
    inspection_row["findings_note"] = note
    # outcome stays null, so a voided inspection can never clear a suspension
    inspection_row["outcome"] = None
    inspection_row["allowed_occupancy_cap"] = 0
    touch(inspection_row)
    return object_response(public(inspection_row))
