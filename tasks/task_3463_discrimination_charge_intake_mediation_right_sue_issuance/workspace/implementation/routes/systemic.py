"""Systemic cases: open and link charges (PRD 3.9)."""

from flask import Blueprint

import constants
import serializers
from domain import cascades
from errors import (
    ApiError,
    ERR_CHARGE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_SYSTEMIC_CASE_NOT_FOUND,
)
from helpers import (
    authenticate,
    bump,
    common_fields,
    request_body,
    require_roles,
    respond_object,
)
from store import db
from validation import req_enum_array, req_string

bp = Blueprint("systemic", __name__, url_prefix="/eeoc")


@bp.post("/systemic-cases")
def create_systemic_case():
    user_id, role = authenticate()
    require_roles(role, (constants.ROLE_COMMISSIONER,))
    body = request_body()
    title = req_string(body, "title")
    basis_focus = req_enum_array(body, "basis_focus", constants.BASIS_CODES)

    systemic_case = {
        **common_fields(),
        "title": title,
        "basis_focus": basis_focus,
        "commissioner_user_id": user_id,
        "status": constants.SYSTEMIC_OPENED,
        "linked_charge_count": 0,
    }
    db.systemic_cases[systemic_case["id"]] = systemic_case
    return respond_object(
        serializers.serialize_systemic_case(systemic_case), status=201
    )


@bp.post("/systemic-cases/<systemic_case_id>/links")
def link_charge(systemic_case_id):
    _, role = authenticate()
    require_roles(role, (constants.ROLE_COMMISSIONER,))
    # Step 3: schema.
    body = request_body()
    charge_id = req_string(body, "charge_id")
    # Step 4: existence -- path id first, then the body reference.
    systemic_case = db.systemic_cases.get(systemic_case_id)
    if systemic_case is None:
        raise ApiError(
            ERR_SYSTEMIC_CASE_NOT_FOUND, "No systemic case with the given id."
        )
    charge = db.charges.get(charge_id)
    if charge is None:
        raise ApiError(ERR_CHARGE_NOT_FOUND, "No charge with the given id.")
    # Link gates (ERR_INVALID_STATE per the validation table): the case must
    # not be RESOLVED, the charge must be non-terminal (per the section 3.9
    # terminal set, which includes CLOSED_SETTLED) and not already linked.
    if systemic_case["status"] == constants.SYSTEMIC_RESOLVED:
        raise ApiError(
            ERR_INVALID_STATE, "Cannot link into a RESOLVED systemic case."
        )
    if charge["case_status"] in constants.SYSTEMIC_TERMINAL_CHARGE_STATES:
        raise ApiError(
            ERR_INVALID_STATE,
            "Only a non-terminal charge can be linked into a systemic case.",
        )
    if charge["systemic_case_id"] is not None:
        raise ApiError(
            ERR_INVALID_STATE, "Charge is already linked to a systemic case."
        )

    # Linking sets the FK, seals the charge, engages the priority multiplier
    # (via systemic_case_id in the score formula), and re-evaluates
    # consolidation.
    charge["systemic_case_id"] = systemic_case["id"]
    charge["disclosure_hold"] = constants.HOLD_SEALED
    bump(charge)
    cascades.reeval_systemic(systemic_case)
    return respond_object(
        serializers.serialize_systemic_case(systemic_case), status=200
    )
