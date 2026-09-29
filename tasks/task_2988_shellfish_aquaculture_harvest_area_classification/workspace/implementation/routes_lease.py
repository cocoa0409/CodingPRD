"""Leases: drafting, submission and resubmission, the two clearance legs and
the authority's decision (PRD 3.4).
"""

from flask import Blueprint

import serializers as ser
from core import (
    GEAR_TYPES,
    LEASE_STATUSES,
    MAX_REVISION_ROUNDS,
    ROLE_AUTHORITY,
    ROLE_OPERATOR,
    ROLE_REVIEWER,
    acting_user,
    apply_changes,
    authenticate,
    body_ref,
    clock,
    db,
    envelope_array,
    envelope_object,
    f_date,
    f_enum,
    f_int,
    f_num,
    f_str,
    f_str_list,
    get_area,
    get_lease,
    json_body,
    pagination,
    paginate,
    q,
    q_enum,
    q_str,
    require_lease_owner,
    sort_default,
    stamp_new,
)
from errors import ApiError

bp = Blueprint("leases", __name__)

LEASE_READ_ROLES = [ROLE_AUTHORITY, ROLE_REVIEWER, ROLE_OPERATOR]


@bp.route("/leases", methods=["POST"])
def draft_lease():
    authenticate([ROLE_OPERATOR])
    body = json_body()
    # Rung 3 — body references resolve before the rest of the shape is judged.
    area = get_area(body_ref(body, "growing_area_id", "ERR_GROWING_AREA_NOT_FOUND"))
    lease_code = f_str(body, "lease_code")
    requested_acreage = f_num(body, "requested_acreage", exclusive_minimum=0)
    plot_codes = f_str_list(
        body, "plot_codes", min_items=1, max_items=12, unique=True
    )
    gear_types = f_str_list(
        body, "gear_types_permitted", min_items=1, unique=True, members=GEAR_TYPES
    )
    authorized_gear_units = f_int(body, "authorized_gear_units", minimum=1)

    lease = {
        "growing_area_id": area["id"],
        "operator_user_id": acting_user(),
        "lease_code": lease_code,
        "requested_acreage": requested_acreage,
        "plot_codes": list(plot_codes),
        "gear_types_permitted": list(gear_types),
        "authorized_gear_units": authorized_gear_units,
        "deployed_gear_units": 0,
        "status": "DRAFT",
        "navigation_clearance": "PENDING",
        "environmental_clearance": "PENDING",
        "navigation_reviewer_user_id": None,
        "environmental_reviewer_user_id": None,
        "revision_round": 0,
        "rent_paid_through_date": None,
        "royalty_accrued_cents": 0,
        "decided_at": None,
    }
    stamp_new(lease)
    db.leases[lease["id"]] = lease
    return envelope_object(ser.lease(lease)), 201


@bp.route("/leases/<lease_id>", methods=["GET"])
def read_lease(lease_id):
    authenticate(LEASE_READ_ROLES)
    lease = get_lease(lease_id)
    return envelope_object(ser.lease(lease)), 200


@bp.route("/leases", methods=["GET"])
def list_leases():
    authenticate(LEASE_READ_ROLES)
    limit, offset = pagination()
    growing_area_id = q_str("growing_area_id")
    operator_user_id = q_str("operator_user_id")
    status = q_enum("status", LEASE_STATUSES)
    rows = []
    for lease in db.leases.values():
        if growing_area_id is not None and lease["growing_area_id"] != growing_area_id:
            continue
        if (
            operator_user_id is not None
            and lease["operator_user_id"] != operator_user_id
        ):
            continue
        if status is not None and lease["status"] != status:
            continue
        rows.append(lease)
    rows = sort_default(rows)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return envelope_array([ser.lease(r) for r in page], limit, offset, total), 200


@bp.route("/leases/<lease_id>/submit", methods=["POST"])
def submit_lease(lease_id):
    authenticate([ROLE_OPERATOR])
    lease = get_lease(lease_id)
    require_lease_owner(lease)
    body = json_body()
    f_str(body, "submission_note", required=False, default=None)

    # Rung 7 — only a draft or a returned application may be submitted.
    if lease["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_LEASE_STATE")
    # Rung 8 — a prohibited area accepts no application.
    area = db.growing_areas.get(lease["growing_area_id"])
    if area is not None and area["classification"] == "PROHIBITED":
        raise ApiError("ERR_AREA_PROHIBITED")
    # Rung 12 — the revision cycle has a hard limit.
    resubmission = lease["status"] == "REVISION_REQUESTED"
    if resubmission and lease["revision_round"] >= MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_EXCEEDED")

    changes = {
        "status": "UNDER_REVIEW",
        "navigation_clearance": "PENDING",
        "environmental_clearance": "PENDING",
        "navigation_reviewer_user_id": None,
        "environmental_reviewer_user_id": None,
    }
    if resubmission:
        changes["revision_round"] = lease["revision_round"] + 1
    apply_changes(lease, changes)
    return envelope_object(ser.lease(lease)), 200


def _record_review(lease_id, leg):
    authenticate([ROLE_REVIEWER])
    lease = get_lease(lease_id)
    body = json_body()
    decision = f_enum(body, "decision", ["CLEARED", "OBJECTION"])
    f_str(body, "review_note", required=False, default=None)

    if leg == "navigation":
        own_field = "navigation_clearance"
        own_reviewer = "navigation_reviewer_user_id"
        sibling_field = "environmental_clearance"
        sibling_reviewer = "environmental_reviewer_user_id"
    else:
        own_field = "environmental_clearance"
        own_reviewer = "environmental_reviewer_user_id"
        sibling_field = "navigation_clearance"
        sibling_reviewer = "navigation_reviewer_user_id"

    # Rung 7 — the lease must be under review and the addressed leg pending.
    if lease["status"] != "UNDER_REVIEW" or lease[own_field] != "PENDING":
        raise ApiError("ERR_INVALID_LEASE_STATE")
    # Rung 12 — one human may not sign off both legs of the same lease.
    if (
        lease[sibling_reviewer] is not None
        and lease[sibling_reviewer] == acting_user()
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    changes = {own_field: decision, own_reviewer: acting_user()}
    if decision == "CLEARED":
        if lease[sibling_field] == "CLEARED":
            changes["status"] = "PENDING_DECISION"
    else:
        changes["status"] = "REVISION_REQUESTED"
        if leg == "environmental":
            # An environmental objection moves the footprint, so any navigation
            # finding about the old footprint is worthless.
            changes["navigation_clearance"] = "PENDING"
            changes["navigation_reviewer_user_id"] = None
    apply_changes(lease, changes)
    return envelope_object(ser.lease(lease)), 200


@bp.route("/leases/<lease_id>/navigation-review", methods=["POST"])
def navigation_review(lease_id):
    return _record_review(lease_id, "navigation")


@bp.route("/leases/<lease_id>/environmental-review", methods=["POST"])
def environmental_review(lease_id):
    return _record_review(lease_id, "environmental")


@bp.route("/leases/<lease_id>/decision", methods=["POST"])
def decide_lease(lease_id):
    authenticate([ROLE_AUTHORITY])
    lease = get_lease(lease_id)
    body = json_body()
    decision = f_enum(body, "decision", ["APPROVE", "DENY"])
    rent_paid_through_date = f_date(
        body, "rent_paid_through_date", required=False, default=None
    )
    f_str(body, "decision_note", required=False, default=None)

    # Rung 7 — the application must have cleared both legs.
    if lease["status"] != "PENDING_DECISION":
        raise ApiError("ERR_INVALID_LEASE_STATE")
    if (
        lease["navigation_clearance"] != "CLEARED"
        or lease["environmental_clearance"] != "CLEARED"
    ):
        raise ApiError("ERR_INVALID_LEASE_STATE")
    # Rung 8 — the guard is scoped to the capability, not to one outcome.
    area = db.growing_areas.get(lease["growing_area_id"])
    if area is not None and area["classification"] == "PROHIBITED":
        raise ApiError("ERR_AREA_PROHIBITED")

    if decision == "APPROVE":
        if rent_paid_through_date is None:
            rent_paid_through_date = clock.today()
        apply_changes(
            lease,
            {
                "status": "APPROVED",
                "decided_at": clock.now(),
                "rent_paid_through_date": rent_paid_through_date,
            },
        )
    else:
        apply_changes(
            lease, {"status": "DENIED", "decided_at": clock.now()}
        )
    return envelope_object(ser.lease(lease)), 200
