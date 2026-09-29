"""Ride-operator certifications with half-open validity intervals."""

from flask import Blueprint

import derive
import fetch
import store
import validate
from auth import ALL_ROLES, require_roles
from envelope import list_response
from errors import (
    fail,
    invalid,
    ERR_CERTIFICATION_STATE_INVALID,
    ERR_CERTIFICATION_WINDOW_OVERLAP,
)
from reply import computed, made, saved

bp = Blueprint("certifications", __name__)


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection of positive duration."""
    return max(a_start, b_start) < min(a_end, b_end)


@bp.post("/park-ops/operator-certifications")
@require_roles("MaintenanceManager")
def create_certification():
    data = validate.body()
    attraction = fetch.fk("attractions", data.get("attraction_id"))
    validate.id_field(data, "attraction_id")
    operator_user_id = validate.str_field(data, "operator_user_id")
    effective_from = validate.instant_field(data, "effective_from")
    expires_at = validate.instant_field(data, "expires_at")
    restraint = validate.int_field(data, "restraint_verification_score",
                                  minimum=0, maximum=100)
    dispatch = validate.int_field(data, "dispatch_procedure_score",
                                  minimum=0, maximum=100)
    if expires_at <= effective_from:
        invalid("expires_at must be strictly after effective_from.")
    for existing in store.rows("certifications"):
        if (existing["attraction_id"] != attraction["id"]
                or existing["operator_user_id"] != operator_user_id):
            continue
        if _overlaps(effective_from, expires_at,
                     store.instant_of(existing["effective_from"]),
                     store.instant_of(existing["expires_at"])):
            fail(ERR_CERTIFICATION_WINDOW_OVERLAP,
                 "This operator already holds a certification whose validity "
                 "interval overlaps the requested one on this attraction.")
    row = store.create(
        "certifications",
        attraction_id=attraction["id"],
        operator_user_id=operator_user_id,
        effective_from=store.iso(effective_from),
        expires_at=store.iso(expires_at),
        restraint_verification_score=restraint,
        dispatch_procedure_score=dispatch,
        suspended_at=None,
        suspension_reason=None,
    )
    return made(derive.ser_certification, row)


@bp.get("/park-ops/operator-certifications/<certification_id>")
@require_roles(*ALL_ROLES)
def read_certification(certification_id):
    return computed(derive.ser_certification(
        fetch.certification(certification_id)))


@bp.get("/park-ops/operator-certifications")
@require_roles(*ALL_ROLES)
def list_certifications():
    return list_response(
        store.rows("certifications"),
        derive.ser_certification,
        filters=(("attraction_id", "str"), ("operator_user_id", "str"),
                 ("status", "str")),
        order=("effective_from",),
    )


@bp.post("/park-ops/operator-certifications/<certification_id>/suspend")
@require_roles("SafetyOfficer")
def suspend_certification(certification_id):
    certification = fetch.certification(certification_id)
    data = validate.body()
    reason = validate.str_field(data, "suspension_reason", allow_empty=True)
    if derive.certification_status(certification) != "CERTIFIED":
        fail(ERR_CERTIFICATION_STATE_INVALID,
             "Only a certification whose derived status is CERTIFIED may be "
             "suspended.")
    certification["suspended_at"] = store.now_iso()
    certification["suspension_reason"] = reason
    return saved(derive.ser_certification, certification)
