"""Studio reservations, deposit holds, checkout and return (PRD 3.6 / 3.7)."""

from flask import Blueprint

import calc
import cascades
import constants as C
import db
import middleware
import serialize
import support
import validation
from errors import ApiError, bad_request, invalid_transition, not_found
from util import add_seconds

bp = Blueprint("reservations", __name__)

READ_ROLES = (
    C.ROLE_CENTER_ADMIN,
    C.ROLE_FACILITIES_MANAGER,
    C.ROLE_FINANCE_OFFICER,
    C.ROLE_PRODUCER,
)

OPEN_STATUSES = ("CONFIRMED", "CHECKED_OUT", "DAMAGE_REVIEW")


@bp.post("/reservations")
def create_reservation():
    user_id, role = middleware.authorize(C.ROLE_PRODUCER, C.ROLE_FACILITIES_MANAGER)
    body = validation.body()
    producer_id = validation.req_id(body, "producer_id")
    resource_id = validation.req_id(body, "resource_id")
    start_at = validation.req_datetime(body, "start_at")
    end_at = validation.req_datetime(body, "end_at")
    linked_slot_id = validation.opt_id(body, "linked_slot_id")
    # priority 3
    if end_at <= start_at:
        raise bad_request("end_at must be strictly after start_at")
    # priority 5, in the order the fields are listed
    producer = db.get("producers", producer_id)
    if producer is None:
        raise not_found("producer", producer_id)
    resource = db.get("studio_resources", resource_id)
    if resource is None:
        raise not_found("studio_resource", resource_id)
    slot = None
    if linked_slot_id is not None:
        slot = db.get("playback_slots", linked_slot_id)
        if slot is None:
            raise not_found("playback_slot", linked_slot_id)
    # priority 6
    middleware.require_owner(producer_id, user_id, role)
    # priority 36
    if slot is not None:
        program = db.get("programs", slot["program_id"])
        if program is None or program["producer_id"] != producer_id:
            raise ApiError(
                "ERR_SLOT_PRODUCER_MISMATCH",
                "The linked slot's program belongs to a different producer",
            )
    row = db.new_row(
        "reservations",
        {
            "producer_id": producer_id,
            "resource_id": resource_id,
            "linked_slot_id": linked_slot_id,
            "start_at": start_at,
            "end_at": end_at,
            "status": "REQUESTED",
            "risk_bp": 0,
            "deposit_hold_cents": 0,
            "late_fee_cents": 0,
            "assessed_repair_cents": 0,
            "deposit_forfeited_cents": 0,
            "deposit_refunded_cents": 0,
            "uncovered_liability_cents": 0,
            "checked_out_at": None,
            "returned_at": None,
            "condition_notes": None,
            "cancellation_reason": None,
        },
    )
    return support.created("reservations", row)


@bp.get("/reservations/<reservation_id>")
def read_reservation(reservation_id):
    middleware.authorize(*READ_ROLES)
    row = support.must_exist("reservations", reservation_id)
    return support.single("reservations", row)


@bp.get("/reservations")
def list_reservations():
    middleware.authorize(*READ_ROLES)
    producer_id = validation.query_string("producer_id")
    resource_id = validation.query_string("resource_id")
    linked_slot_id = validation.query_string("linked_slot_id")
    status = validation.query_enum("status", C.RESERVATION_STATUSES)
    validation.pagination()
    rows = support.filter_rows(
        "reservations",
        [
            ("producer_id", producer_id),
            ("resource_id", resource_id),
            ("linked_slot_id", linked_slot_id),
            ("status", status),
        ],
    )
    return support.collection_response("reservations", rows)


def _overbooked(resource, reservation):
    """Capacity count and the trailing turnaround window (PRD 3.6)."""
    others = [
        other
        for other in db.all_rows("reservations")
        if other["resource_id"] == resource["id"]
        and other["id"] != reservation["id"]
        and other["status"] in OPEN_STATUSES
    ]
    overlapping = [
        other
        for other in others
        if calc.intervals_overlap(
            reservation["start_at"], reservation["end_at"], other["start_at"], other["end_at"]
        )
    ]
    if len(overlapping) >= resource["capacity_slots"]:
        return True
    turnaround_seconds = resource["turnaround_minutes"] * 60
    if turnaround_seconds > 0:
        for other in others:
            clear_at = add_seconds(other["end_at"], turnaround_seconds)
            if other["end_at"] <= reservation["start_at"] < clear_at:
                return True
    return False


@bp.post("/reservations/<reservation_id>/confirm")
def confirm_reservation(reservation_id):
    middleware.authorize(C.ROLE_FACILITIES_MANAGER)
    validation.body()
    row = support.must_exist("reservations", reservation_id)
    # priority 9
    if row["status"] != "REQUESTED":
        raise invalid_transition("Only a requested reservation may be confirmed")
    resource = db.get("studio_resources", row["resource_id"])
    producer = db.get("producers", row["producer_id"])
    # priority 14
    if resource is None or resource["status"] != "AVAILABLE":
        raise ApiError("ERR_RESOURCE_NOT_AVAILABLE", "The asset is not available for booking")
    # priority 10
    if producer is None or producer["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCER_NOT_ACTIVE", "The reserving producer is not active")
    # priority 15
    if resource["required_competency_code"] not in calc.competency_codes(producer):
        raise ApiError(
            "ERR_COMPETENCY_NOT_HELD", "The producer does not hold the required equipment competency"
        )
    # priority 29
    if _overbooked(resource, row):
        raise ApiError("ERR_RESOURCE_OVERBOOKED", "The asset has no room for that interval")
    risk, hold = calc.deposit_hold(producer, resource, row)
    # priority 40
    if serialize.deposit_held_cents(producer["id"]) + hold > C.DEPOSIT_HOLD_CAP_CENTS:
        raise ApiError(
            "ERR_DEPOSIT_LIMIT_EXCEEDED", "The producer's aggregate deposit ceiling would be breached"
        )
    row["risk_bp"] = risk
    row["deposit_hold_cents"] = hold
    row["status"] = "CONFIRMED"
    db.bump(row)
    # deposit_held_cents and open_reservation_count are derived invariants (PRD 2.9),
    # so the producer and asset rows are not themselves mutated here.
    return support.single("reservations", row)


@bp.post("/reservations/<reservation_id>/cancel")
def cancel_reservation(reservation_id):
    user_id, role = middleware.authorize(C.ROLE_PRODUCER, C.ROLE_FACILITIES_MANAGER)
    body = validation.body()
    cancellation_reason = validation.req_string(body, "cancellation_reason")
    row = support.must_exist("reservations", reservation_id)
    # priority 6
    middleware.require_owner(row["producer_id"], user_id, role)
    # priority 9
    if row["status"] not in ("REQUESTED", "CONFIRMED"):
        raise invalid_transition("Only a requested or confirmed reservation may be cancelled")
    cascades.cancel_reservation_for_sanction(row, cancellation_reason)
    return support.single("reservations", row)


@bp.post("/reservations/<reservation_id>/checkout")
def checkout_reservation(reservation_id):
    middleware.authorize(C.ROLE_FACILITIES_MANAGER)
    body = validation.body()
    condition_notes = validation.opt_string(body, "condition_notes")
    row = support.must_exist("reservations", reservation_id)
    # priority 9
    if row["status"] != "CONFIRMED":
        raise invalid_transition("Only a confirmed reservation may be checked out")
    producer = db.get("producers", row["producer_id"])
    # priority 10
    if producer is None or producer["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCER_NOT_ACTIVE", "The reserving producer is not active")
    # priority 30
    instant = db.now()
    opens_at = add_seconds(row["start_at"], -C.CHECKOUT_LEAD_SECONDS)
    if instant < opens_at or instant >= row["end_at"]:
        raise ApiError("ERR_CHECKOUT_WINDOW_NOT_OPEN", "The checkout window is not open")
    row["status"] = "CHECKED_OUT"
    row["checked_out_at"] = instant
    row["condition_notes"] = condition_notes
    db.bump(row)
    return support.single("reservations", row)


@bp.post("/reservations/<reservation_id>/return")
def return_reservation(reservation_id):
    user_id, _role = middleware.authorize(C.ROLE_FACILITIES_MANAGER)
    body = validation.body()
    damage_observed = validation.req_bool(body, "damage_observed")
    condition_notes = validation.opt_string(body, "condition_notes")
    severity = None
    repair_estimate_cents = None
    damage_notes = None
    if damage_observed:
        severity = validation.req_enum(body, "severity", C.DAMAGE_SEVERITIES)
        repair_estimate_cents = validation.req_int(body, "repair_estimate_cents", minimum=0)
        damage_notes = validation.opt_string(body, "damage_notes")
    row = support.must_exist("reservations", reservation_id)
    # priority 9
    if row["status"] != "CHECKED_OUT":
        raise invalid_transition("Only a checked-out reservation may be returned")
    resource = db.get("studio_resources", row["resource_id"])
    producer = db.get("producers", row["producer_id"])

    instant = db.now()
    row["returned_at"] = instant
    if condition_notes is not None:
        row["condition_notes"] = condition_notes
    # step one and two of the waterfall run on both branches
    row["late_fee_cents"] = calc.late_fee(resource, row, instant)

    if not damage_observed:
        cascades.settle_reservation(row, 0)
        return support.single("reservations", row)

    row["status"] = "DAMAGE_REVIEW"
    db.bump(row)
    db.new_row(
        "damage_assessments",
        {
            "reservation_id": row["id"],
            "severity": severity,
            "repair_estimate_cents": repair_estimate_cents,
            "assessed_repair_cents": 0,
            "suspension_points_assessed": 0,
            "status": "FILED",
            "filed_by_user_id": user_id,
            "waived_by_user_id": None,
            "waiver_reason": None,
            "damage_notes": damage_notes,
        },
    )
    return support.single("reservations", row)
