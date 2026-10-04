"""Determinations: drafting, submission, Director review (PRD 3.6).

Approving CAUSE drives the three-link cascade (charge -> CONCILIATION ->
ConciliationProcess -> PROVISIONAL RemedyPackage). Approving NO_CAUSE /
UNABLE_TO_DETERMINE closes the charge and auto-issues a right-to-sue notice.
"""

from datetime import timedelta
from flask import Blueprint

import constants
import serializers
from domain import cascades, remedy
from errors import (
    ApiError,
    ERR_CHARGE_ALREADY_CLOSED,
    ERR_DETERMINATION_EXISTS,
    ERR_DETERMINATION_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VALIDATION_FAILED,
)
from helpers import (
    authenticate,
    bump,
    common_fields,
    paginate_and_respond,
    request_body,
    require_roles,
    respond_object,
    today,
)
from store import db
from validation import (
    present_non_null,
    req_date,
    req_enum,
    req_int,
    req_string,
)
from routes.investigation import (
    charge_of_investigation,
    get_investigation_or_404,
    require_assigned_investigator,
)

bp = Blueprint("determinations", __name__, url_prefix="/eeoc")

_REMEDY_COMPONENT_FIELDS = (
    "back_pay_cents",
    "front_pay_cents",
    "compensatory_damages_cents",
    "punitive_damages_cents",
)

_LIST_ROLES = (
    constants.ROLE_INVESTIGATOR,
    constants.ROLE_DIRECTOR,
)


def get_determination_or_404(determination_id):
    determination = db.determinations.get(determination_id)
    if determination is None:
        raise ApiError(
            ERR_DETERMINATION_NOT_FOUND, "No determination with the given id."
        )
    return determination


def determinations_for_investigation(investigation):
    return [
        d
        for d in db.determinations.values()
        if d["investigation_case_id"] == investigation["id"]
    ]


@bp.post("/investigation-cases/<investigation_id>/determinations")
def create_determination(investigation_id):
    user_id, role = authenticate()
    require_roles(role, (constants.ROLE_INVESTIGATOR,))
    # Step 3: schema, including the CAUSE conditional requirements.
    body = request_body()
    outcome = req_enum(body, "outcome", constants.DETERMINATION_OUTCOMES)
    rationale = req_string(body, "rationale")
    components = {}
    if outcome == constants.DET_OUTCOME_CAUSE:
        for field in _REMEDY_COMPONENT_FIELDS:
            components[field] = req_int(body, field, minimum=0)
        harm_start_date = req_date(body, "harm_start_date")
    else:
        for field in _REMEDY_COMPONENT_FIELDS:
            if present_non_null(body, field):
                raise ApiError(
                    ERR_VALIDATION_FAILED,
                    "Field %s must be null unless outcome is CAUSE." % field,
                )
            components[field] = None
        if present_non_null(body, "harm_start_date"):
            raise ApiError(
                ERR_VALIDATION_FAILED,
                "Field harm_start_date must be null unless outcome is CAUSE.",
            )
        harm_start_date = None

    # Step 4: existence.
    investigation = get_investigation_or_404(investigation_id)
    # Step 5: ownership (assigned investigator only).
    require_assigned_investigator(user_id, investigation)
    # Step 6: state -- the case must be GATHERING.
    charge = charge_of_investigation(investigation)
    if charge["case_status"] in constants.CHARGE_TERMINAL_STATES:
        raise ApiError(ERR_CHARGE_ALREADY_CLOSED, "Charge is in a terminal state.")
    if investigation["status"] != constants.INVESTIGATION_GATHERING:
        raise ApiError(
            ERR_INVALID_STATE,
            "Determinations require a GATHERING case (at least one evidence "
            "activity must have occurred).",
        )
    # Step 8: at most one non-terminal determination per investigation.
    for existing in determinations_for_investigation(investigation):
        if existing["status"] in constants.DETERMINATION_NON_TERMINAL_STATES:
            raise ApiError(
                ERR_DETERMINATION_EXISTS,
                "A non-terminal determination already exists for this case.",
            )

    determination = {
        **common_fields(),
        "investigation_case_id": investigation["id"],
        "outcome": outcome,
        "rationale": rationale,
        "back_pay_cents": components["back_pay_cents"],
        "front_pay_cents": components["front_pay_cents"],
        "compensatory_damages_cents": components["compensatory_damages_cents"],
        "punitive_damages_cents": components["punitive_damages_cents"],
        "harm_start_date": harm_start_date,
        "status": constants.DET_DRAFT,
        "prepared_by_user_id": user_id,
        "reviewed_by_user_id": None,
        "return_reason": None,
    }
    db.determinations[determination["id"]] = determination
    return respond_object(
        serializers.serialize_determination(determination), status=201
    )


@bp.get("/investigation-cases/<investigation_id>/determinations")
def list_determinations(investigation_id):
    _, role = authenticate()
    require_roles(role, _LIST_ROLES)
    investigation = get_investigation_or_404(investigation_id)
    rows = determinations_for_investigation(investigation)
    return paginate_and_respond(rows, serializers.serialize_determination)


@bp.post("/determinations/<determination_id>/submit")
def submit_determination(determination_id):
    user_id, role = authenticate()
    require_roles(role, (constants.ROLE_INVESTIGATOR,))
    request_body(required=False)
    determination = get_determination_or_404(determination_id)
    investigation = db.investigation_cases[determination["investigation_case_id"]]
    charge = charge_of_investigation(investigation)

    # Only the drafting investigator may submit (or resubmit from RETURNED).
    if user_id != determination["prepared_by_user_id"]:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            "Only the drafting investigator may submit this determination.",
        )
    if charge["case_status"] in constants.CHARGE_TERMINAL_STATES:
        raise ApiError(ERR_CHARGE_ALREADY_CLOSED, "Charge is in a terminal state.")
    if determination["status"] not in (
        constants.DET_DRAFT,
        constants.DET_RETURNED,
    ):
        raise ApiError(
            ERR_INVALID_STATE,
            "Determination in %s cannot be submitted." % determination["status"],
        )
    if charge["case_status"] != constants.CHARGE_UNDER_INVESTIGATION:
        raise ApiError(
            ERR_INVALID_STATE,
            "Charge in %s cannot enter determination review."
            % charge["case_status"],
        )

    determination["status"] = constants.DET_PENDING_REVIEW
    bump(determination)
    charge["case_status"] = constants.CHARGE_DETERMINATION_REVIEW
    bump(charge)
    return respond_object(
        serializers.serialize_determination(determination), status=200
    )


@bp.post("/determinations/<determination_id>/review")
def review_determination(determination_id):
    user_id, role = authenticate()
    require_roles(role, (constants.ROLE_DIRECTOR,))
    # Step 3: schema -- RETURN requires return_reason; APPROVE forbids it.
    body = request_body()
    decision = req_enum(body, "decision", constants.REVIEW_DECISIONS)
    if decision == constants.DECISION_RETURN:
        return_reason = req_string(body, "return_reason")
    else:
        if present_non_null(body, "return_reason"):
            raise ApiError(
                ERR_VALIDATION_FAILED,
                "return_reason must be null when decision is APPROVE.",
            )
        return_reason = None

    # Step 4: existence.
    determination = get_determination_or_404(determination_id)
    investigation = db.investigation_cases[determination["investigation_case_id"]]
    charge = charge_of_investigation(investigation)

    # Step 6: state.
    if charge["case_status"] in constants.CHARGE_TERMINAL_STATES:
        raise ApiError(ERR_CHARGE_ALREADY_CLOSED, "Charge is in a terminal state.")
    if determination["status"] != constants.DET_PENDING_REVIEW:
        raise ApiError(
            ERR_INVALID_STATE,
            "Determination in %s cannot be reviewed." % determination["status"],
        )
    # Step 7: segregation of duties -- reviewer != drafting investigator.
    if user_id == determination["prepared_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "The reviewing Director must differ from the drafting investigator.",
        )

    determination["reviewed_by_user_id"] = user_id

    if decision == constants.DECISION_RETURN:
        determination["return_reason"] = return_reason
        determination["status"] = constants.DET_RETURNED
        bump(determination)
        charge["case_status"] = constants.CHARGE_UNDER_INVESTIGATION
        bump(charge)
        return respond_object(
            serializers.serialize_determination(determination), status=200
        )

    # APPROVE -------------------------------------------------------------
    determination["status"] = constants.DET_APPROVED
    bump(determination)

    # Either approval cascade closes the investigation and waives its open
    # evidence requests.
    cascades.close_investigation(investigation)

    if determination["outcome"] == constants.DET_OUTCOME_CAUSE:
        # Link 1: charge -> CONCILIATION.
        charge["case_status"] = constants.CHARGE_CONCILIATION
        bump(charge)
        # Link 2: entering CONCILIATION auto-creates the ConciliationProcess.
        conciliation = {
            **common_fields(),
            "charge_id": charge["id"],
            "origin_determination_id": determination["id"],
            "status": constants.CONC_INITIATED,
            "current_offer_cents": None,
            "last_offer_by": None,
            "rounds_count": 0,
        }
        db.conciliation_processes[conciliation["id"]] = conciliation
        # Link 3: its creation auto-creates the PROVISIONAL RemedyPackage.
        employer = db.employers[charge["employer_id"]]
        package = {
            **common_fields(),
            "conciliation_process_id": conciliation["id"],
            "valuation_variant": constants.VALUATION_PROVISIONAL,
            "back_pay_cents": determination["back_pay_cents"],
            "front_pay_cents": determination["front_pay_cents"],
            "compensatory_damages_cents": determination[
                "compensatory_damages_cents"
            ],
            "punitive_damages_cents": determination["punitive_damages_cents"],
            "harm_start_date": determination["harm_start_date"],
            "band_used": None,
            "projection_date": None,
            "interest_days": 0,
            "back_pay_interest_cents": 0,
            "front_pay_interest_cents": 0,
            "capped_nonpecuniary_cents": 0,
            "total_cents": 0,
        }
        # PROVISIONAL: band from the employer's current size_band; interest
        # accrues to the conciliation-initiation date.
        remedy.compute_remedy(package, employer["size_band"], today())
        db.remedy_packages[package["id"]] = package
    else:
        # NO_CAUSE / UNABLE_TO_DETERMINE: close the charge and auto-issue the
        # right-to-sue notice.
        charge["case_status"] = constants.CHARGE_CLOSED_NO_CAUSE
        bump(charge)
        issued = today()
        notice = {
            **common_fields(),
            "charge_id": charge["id"],
            "issuance_basis": constants.RTS_BASIS_AUTO,
            "requested_by_role": constants.RTS_SYSTEM_REQUESTER,
            "issued_date": issued,
            "court_filing_deadline": issued
            + timedelta(days=constants.RTS_COURT_FILING_DAYS),
            "status": constants.RTS_ISSUED,
        }
        db.right_to_sue_notices[notice["id"]] = notice

    cascades.reeval_systemic_for_charge(charge)
    return respond_object(
        serializers.serialize_determination(determination), status=200
    )
