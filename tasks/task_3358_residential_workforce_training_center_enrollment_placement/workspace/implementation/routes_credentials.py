"""Credentials: record, list, verify/revoke with remediation auto-advance."""
from flask import Blueprint

from auth import authenticate, require_role
from db import STORE, new_record, bump
from envelope import ok_object, ok_list
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE,
    ERR_CONDUCT_HOLD,
)
from helpers import (
    get_body,
    check_unknown,
    as_str,
    as_enum,
    pagination_params,
    paginate,
)
import domain
import serializers

bp = Blueprint("credentials", __name__)

CREDENTIAL_TYPES = {"HSE", "INDUSTRY_CERT", "DRIVER_LICENSE"}
CREDENTIAL_ACTIONS = ["verify", "revoke"]


@bp.route("/jc/credentials", methods=["POST"])
def create_credential():
    user_id, role = authenticate()
    require_role(role, {"CareerInstructor"})
    body = get_body()
    check_unknown(body, {"enrollment_id", "credential_type", "subject_area"})
    enrollment_id = as_str(body, "enrollment_id", required=True)
    credential_type = as_enum(body, "credential_type", sorted(CREDENTIAL_TYPES), required=True)
    subject_area = as_str(body, "subject_area")
    if credential_type == "INDUSTRY_CERT" and subject_area is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            ERR_INVALID_REQUEST[1],
            "subject_area is required for INDUSTRY_CERT",
        )
    enrollment = STORE.enrollments.get(enrollment_id)
    if enrollment is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Enrollment not found")
    # Priority 9: conduct hold gates credential writes.
    domain.recompute_conduct_hold(enrollment_id)
    if enrollment["conduct_hold"]:
        raise ApiError(
            ERR_CONDUCT_HOLD[0],
            ERR_CONDUCT_HOLD[1],
            "Enrollment conduct_hold is active",
        )
    rec = new_record()
    rec.update(
        {
            "enrollment_id": enrollment_id,
            "credential_type": credential_type,
            "subject_area": subject_area,
            "status": "EARNED",
            "earned_at": STORE.clock_date_str(),
            "verified_at": None,
        }
    )
    STORE.credentials[rec["id"]] = rec
    return ok_object(serializers.credential_view(rec), status=201)


@bp.route("/jc/enrollments/<enrollment_id>/credentials", methods=["GET"])
def list_enrollment_credentials(enrollment_id):
    user_id, role = authenticate()
    require_role(role, {"CareerInstructor", "EnrollmentManager"})
    if enrollment_id not in STORE.enrollments:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Enrollment not found")
    limit, offset = pagination_params()
    items = [c for c in STORE.credentials.values() if c["enrollment_id"] == enrollment_id]
    items.sort(key=lambda c: c["_seq"])
    page, meta = paginate([serializers.credential_view(c) for c in items], limit, offset)
    return ok_list(page, meta)


@bp.route("/jc/credentials/<credential_id>/transition", methods=["POST"])
def credential_transition(credential_id):
    user_id, role = authenticate()
    require_role(role, {"CareerInstructor"})
    cred = STORE.credentials.get(credential_id)
    if cred is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Credential not found")
    body = get_body()
    check_unknown(body, {"action"})
    action = as_enum(body, "action", CREDENTIAL_ACTIONS, required=True)
    # Priority 7: REVOKED is terminal.
    if cred["status"] == "REVOKED":
        raise ApiError(
            ERR_ALREADY_TERMINAL[0],
            ERR_ALREADY_TERMINAL[1],
            "Credential is REVOKED (terminal)",
        )
    if action == "verify":
        if cred["status"] != "EARNED":
            _invalid_state(action, cred["status"])
        cred["status"] = "VERIFIED"
        cred["verified_at"] = STORE.clock_date_str()
        bump(cred)
        # Remediation auto-advance: when this verification completes the
        # program's required set on this enrollment's own credentials.
        enrollment = STORE.enrollments.get(cred["enrollment_id"])
        if enrollment is not None and enrollment["training_status"] == "REMEDIATION":
            if domain.prereqs_met_for_enrollment(enrollment):
                enrollment["training_status"] = "TRAINING"
                bump(enrollment)
    elif action == "revoke":
        if cred["status"] != "VERIFIED":
            _invalid_state(action, cred["status"])
        # Revocation never demotes an enrollment already in TRAINING.
        cred["status"] = "REVOKED"
        bump(cred)
    return ok_object(serializers.credential_view(cred), status=200)


def _invalid_state(action, status):
    raise ApiError(
        ERR_INVALID_STATE[0],
        ERR_INVALID_STATE[1],
        "Action {} is not defined from state {}".format(action, status),
    )
