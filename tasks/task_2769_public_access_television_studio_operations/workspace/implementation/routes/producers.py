"""Membership admission, reinstatement and revocation (PRD 3.1 / 3.7)."""

from flask import Blueprint

import cascades
import constants as C
import db
import middleware
import support
import validation
from errors import ApiError, invalid_transition

bp = Blueprint("producers", __name__)

READ_ONE_ROLES = (
    C.ROLE_CENTER_ADMIN,
    C.ROLE_TRAINING_COORDINATOR,
    C.ROLE_CONTENT_REVIEWER,
    C.ROLE_SCHEDULING_COORDINATOR,
    C.ROLE_FACILITIES_MANAGER,
    C.ROLE_FINANCE_OFFICER,
    C.ROLE_PRODUCER,
)

LIST_ROLES = (
    C.ROLE_CENTER_ADMIN,
    C.ROLE_TRAINING_COORDINATOR,
    C.ROLE_SCHEDULING_COORDINATOR,
    C.ROLE_FACILITIES_MANAGER,
)


@bp.post("/producers")
def create_producer():
    middleware.authorize(C.ROLE_CENTER_ADMIN)
    body = validation.body()
    legal_name = validation.req_string(body, "legal_name")
    email = validation.req_string(body, "email")
    # priority 38: e-mail is a natural key
    for row in db.all_rows("producers"):
        if row["email"] == email:
            raise ApiError("ERR_DUPLICATE_NATURAL_KEY", "A producer with this email already exists")
    row = db.new_row(
        "producers",
        {
            "legal_name": legal_name,
            "email": email,
            "residency_verified": False,
            "status": "APPLICANT",
            "suspension_points": 0,
            "indemnification_expires_at": None,
            "reinstated_count": 0,
            "revocation_reason": None,
        },
    )
    return support.created("producers", row)


@bp.get("/producers/<producer_id>")
def read_producer(producer_id):
    middleware.authorize(*READ_ONE_ROLES)
    row = support.must_exist("producers", producer_id)
    return support.single("producers", row)


@bp.get("/producers")
def list_producers():
    middleware.authorize(*LIST_ROLES)
    status = validation.query_enum("status", C.PRODUCER_STATUSES)
    certification_level = validation.query_enum("certification_level", C.CERTIFICATION_LEVELS)
    validation.pagination()
    rows = support.filter_rows("producers", [("status", status)])
    if certification_level is not None:
        import calc

        rows = [row for row in rows if calc.certification_level(row) == certification_level]
    return support.collection_response("producers", rows)


@bp.post("/producers/<producer_id>/residency-verification")
def verify_residency(producer_id):
    middleware.authorize(C.ROLE_CENTER_ADMIN)
    body = validation.body()
    document_reference = validation.req_string(body, "document_reference")
    row = support.must_exist("producers", producer_id)
    # one-shot: APPLICANT and not yet verified
    if row["status"] != "APPLICANT" or row["residency_verified"]:
        raise invalid_transition("Residency verification is only available to an unverified applicant")
    row["residency_verified"] = True
    row["status"] = "ACTIVE"
    row["residency_document_reference"] = document_reference
    db.bump(row)
    return support.single("producers", row)


@bp.post("/producers/<producer_id>/reinstate")
def reinstate_producer(producer_id):
    middleware.authorize(C.ROLE_CENTER_ADMIN)
    body = validation.body()
    credited = validation.req_int(body, "suspension_points_credited", minimum=0)
    reason = validation.req_string(body, "reason")
    row = support.must_exist("producers", producer_id)
    if row["status"] != "SUSPENDED":
        raise invalid_transition("Only a suspended producer may be reinstated")
    if credited <= 0 or credited > row["suspension_points"]:
        raise invalid_transition(
            "suspension_points_credited must be positive and no greater than the outstanding total"
        )
    remainder = row["suspension_points"] - credited
    if remainder >= C.SUSPENSION_THRESHOLD_POINTS:
        raise invalid_transition("The remaining suspension points would re-cross the threshold")
    row["suspension_points"] = remainder
    row["reinstated_count"] = row["reinstated_count"] + 1
    row["status"] = "ACTIVE"
    row["reinstatement_reason"] = reason
    db.bump(row)
    return support.single("producers", row)


@bp.post("/producers/<producer_id>/revoke")
def revoke_producer(producer_id):
    middleware.authorize(C.ROLE_CENTER_ADMIN)
    body = validation.body()
    revocation_reason = validation.req_string(body, "revocation_reason")
    row = support.must_exist("producers", producer_id)
    if row["status"] not in ("ACTIVE", "SUSPENDED"):
        raise invalid_transition("Only an active or suspended membership may be revoked")
    cascades.revoke_producer(row, revocation_reason)
    return support.single("producers", row)
