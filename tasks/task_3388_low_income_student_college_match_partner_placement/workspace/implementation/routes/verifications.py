"""IncomeVerification endpoints: submit document-verified figures, decide."""
from flask import Blueprint

import serializers
import store
from auth import identity, require_roles
from calculations import discrepancy_outcome
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_WRONG_CYCLE_PHASE,
)
from response import ok_object
from validation import KIND_ENUM, KIND_INT, KIND_STR, get_body, validate

bp = Blueprint("verifications", __name__)

# Submission and decision are permitted during these four phases only
# (PRD section 2.7).
VERIFICATION_PHASES = ("REVIEW", "RANKING", "MATCH_RUN", "REGULAR_DECISION")
DECISIONS = ("VERIFY", "WAIVE")


def _check_phase(application):
    cycle = store.cycles.get(application["cycle_id"])
    if cycle is None or cycle["phase"] not in VERIFICATION_PHASES:
        raise ApiError(
            ERR_WRONG_CYCLE_PHASE,
            "income verification is permitted only in REVIEW, RANKING, MATCH_RUN, or REGULAR_DECISION",
        )
    return cycle


@bp.post("/income-verifications")
def create_verification():
    body = get_body()
    values = validate(body, [
        ("application_id", KIND_STR, True, None, None),
        ("verified_income_cents", KIND_INT, True, None, None),
        ("verified_assets_cents", KIND_INT, True, None, None),
        ("verified_household_size", KIND_INT, True, None, None),
    ])
    role, uid = identity()
    require_roles(role, ("Counselor", "PartnerStaff"))
    application = store.applications.get(values["application_id"])
    if application is None:
        raise ApiError(ERR_NOT_FOUND, "application not found")
    _check_phase(application)
    # The filer's identity lands in exactly one of the two slots.
    verification = store.create(store.verifications, {
        "application_id": application["id"],
        "submitted_by_counselor_id": uid if role == "Counselor" else None,
        "submitted_by_partner_id": uid if role == "PartnerStaff" else None,
        "verified_income_cents": values["verified_income_cents"],
        "verified_assets_cents": values["verified_assets_cents"],
        "verified_household_size": values["verified_household_size"],
        "outcome": "PENDING",
        "decided_by_partner_id": None,
    })
    return ok_object(serializers.verification(verification), 201)


@bp.post("/income-verifications/<verification_id>/decide")
def decide_verification(verification_id):
    body = get_body()
    values = validate(body, [("decision", KIND_ENUM, True, None, DECISIONS)])
    role, uid = identity()
    require_roles(role, ("PartnerStaff",))
    verification = store.verifications.get(verification_id)
    if verification is None:
        raise ApiError(ERR_NOT_FOUND, "income verification not found")
    if verification["outcome"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "only a PENDING verification can be decided")
    application = store.applications.get(verification["application_id"])
    if application is None:
        raise ApiError(ERR_NOT_FOUND, "application not found")
    _check_phase(application)
    # Segregation of duties: the deciding partner must not be the partner that
    # submitted the documents nor the partner that referred the application.
    if verification["submitted_by_partner_id"] is not None and uid == verification["submitted_by_partner_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "the deciding partner submitted this verification")
    if application["referral_id"]:
        referral = store.referrals.get(application["referral_id"])
        if referral is not None and referral["partner_id"] is not None and referral["partner_id"] == uid:
            raise ApiError(ERR_SEGREGATION_OF_DUTIES, "the deciding partner referred this application")

    if values["decision"] == "VERIFY":
        outcome = discrepancy_outcome(
            application["household_income_cents"],
            verification["verified_income_cents"],
        )
    else:  # WAIVE skips the arithmetic entirely
        outcome = "WAIVED"
    verification["outcome"] = outcome
    verification["decided_by_partner_id"] = uid
    store.touch(verification)
    # The application's verification_flag mirrors the outcome.
    application["verification_flag"] = outcome
    store.touch(application)
    return ok_object(serializers.verification(verification))
