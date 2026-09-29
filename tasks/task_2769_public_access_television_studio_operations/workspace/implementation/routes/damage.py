"""Damage assessments: finalization, waiver and the suspension cascade (PRD 3.7)."""

from flask import Blueprint

import calc
import cascades
import constants as C
import db
import middleware
import support
import validation
from errors import ApiError, invalid_transition

bp = Blueprint("damage", __name__)

READ_ROLES = (
    C.ROLE_CENTER_ADMIN,
    C.ROLE_FACILITIES_MANAGER,
    C.ROLE_FINANCE_OFFICER,
    C.ROLE_PRODUCER,
)


@bp.get("/damage-assessments/<assessment_id>")
def read_assessment(assessment_id):
    middleware.authorize(*READ_ROLES)
    row = support.must_exist("damage_assessments", assessment_id)
    return support.single("damage_assessments", row)


@bp.get("/damage-assessments")
def list_assessments():
    middleware.authorize(*READ_ROLES)
    reservation_id = validation.query_string("reservation_id")
    status = validation.query_enum("status", C.DAMAGE_STATUSES)
    severity = validation.query_enum("severity", C.DAMAGE_SEVERITIES)
    validation.pagination()
    rows = support.filter_rows(
        "damage_assessments",
        [("reservation_id", reservation_id), ("status", status), ("severity", severity)],
    )
    return support.collection_response("damage_assessments", rows)


@bp.post("/damage-assessments/<assessment_id>/finalize")
def finalize_assessment(assessment_id):
    middleware.authorize(C.ROLE_FACILITIES_MANAGER)
    validation.body()
    row = support.must_exist("damage_assessments", assessment_id)
    reservation = db.get("reservations", row["reservation_id"])
    # priority 9
    if row["status"] != "FILED" or reservation is None or reservation["status"] != "DAMAGE_REVIEW":
        raise invalid_transition(
            "Only a filed assessment on a reservation under damage review may be finalized"
        )
    resource = db.get("studio_resources", reservation["resource_id"])
    assessed, points = calc.damage_penalty(row, resource)
    row["assessed_repair_cents"] = assessed
    row["suspension_points_assessed"] = points
    row["status"] = "FINALIZED"
    db.bump(row)

    # the join point: the reservation settles with the assessed repair in the waterfall
    cascades.settle_reservation(reservation, assessed)

    producer = db.get("producers", reservation["producer_id"])
    if producer is not None and points:
        producer["suspension_points"] = producer["suspension_points"] + points
        db.bump(producer)
        cascades.suspend_producer_if_due(producer)
    return support.single("damage_assessments", row)


@bp.post("/damage-assessments/<assessment_id>/waive")
def waive_assessment(assessment_id):
    user_id, _role = middleware.authorize(C.ROLE_FINANCE_OFFICER)
    body = validation.body()
    waiver_reason = validation.req_string(body, "waiver_reason")
    row = support.must_exist("damage_assessments", assessment_id)
    # priority 7 runs ahead of the state check
    if row["filed_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "The user who filed an assessment may not waive it"
        )
    reservation = db.get("reservations", row["reservation_id"])
    # priority 9
    if row["status"] != "FILED" or reservation is None or reservation["status"] != "DAMAGE_REVIEW":
        raise invalid_transition(
            "Only a filed assessment on a reservation under damage review may be waived"
        )
    row["assessed_repair_cents"] = 0
    row["suspension_points_assessed"] = 0
    row["status"] = "WAIVED"
    row["waived_by_user_id"] = user_id
    row["waiver_reason"] = waiver_reason
    db.bump(row)
    cascades.settle_reservation(reservation, 0)
    return support.single("damage_assessments", row)
