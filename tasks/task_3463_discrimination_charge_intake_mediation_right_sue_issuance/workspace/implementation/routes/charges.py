"""Charge intake, detail, list, amend, and withdraw (PRD 3.2 and 3.3)."""

from flask import Blueprint

import constants
import serializers
from domain import cascades, screening
from errors import (
    ApiError,
    ERR_CHARGE_ALREADY_CLOSED,
    ERR_CHARGE_NOT_FOUND,
    ERR_COMPLAINANT_NOT_FOUND,
    ERR_CONFIDENTIALITY_SEALED,
    ERR_EMPLOYER_NOT_FOUND,
    ERR_INCIDENT_DATE_FUTURE,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_STALE_VERSION,
)
from helpers import (
    authenticate,
    bump,
    check_party_ownership,
    common_fields,
    paginate_and_respond,
    request_body,
    require_roles,
    respond_object,
    today,
)
from store import db
from validation import (
    opt_date,
    opt_enum_array,
    opt_string,
    req_enum_array,
    req_date,
    req_int,
    req_string,
)

bp = Blueprint("charges", __name__, url_prefix="/eeoc")

_DETAIL_ROLES = (
    constants.ROLE_INTAKE_OFFICER,
    constants.ROLE_CHARGING_PARTY,
    constants.ROLE_RESPONDENT_REP,
    constants.ROLE_INVESTIGATOR,
    constants.ROLE_MEDIATOR,
    constants.ROLE_DIRECTOR,
    constants.ROLE_COMMISSIONER,
    constants.ROLE_STATE_AGENCY_OFFICER,
)

_LIST_ROLES = (
    constants.ROLE_INTAKE_OFFICER,
    constants.ROLE_INVESTIGATOR,
    constants.ROLE_DIRECTOR,
    constants.ROLE_COMMISSIONER,
    constants.ROLE_STATE_AGENCY_OFFICER,
)


def get_charge_or_404(charge_id):
    charge = db.charges.get(charge_id)
    if charge is None:
        raise ApiError(ERR_CHARGE_NOT_FOUND, "No charge with the given id.")
    return charge


def run_dismissal_cascade(charge, new_status):
    """The charge flips to a DISMISSED_* terminal state: owner -> NONE, open
    mediations DECLINED (sessions CANCELLED), investigation CLOSED with its
    open requests WAIVED."""
    charge["case_status"] = new_status
    charge["investigation_owner"] = constants.OWNER_NONE
    cascades.decline_open_mediations(charge)
    investigation = cascades.investigation_for_charge(charge)
    if investigation is not None:
        cascades.close_investigation(investigation)
    cascades.reeval_systemic_for_charge(charge)


@bp.post("/charges")
def create_charge():
    user_id, role = authenticate()
    require_roles(
        role, (constants.ROLE_INTAKE_OFFICER, constants.ROLE_CHARGING_PARTY)
    )
    # Step 3: schema.
    body = request_body()
    complainant_id = req_string(body, "complainant_id")
    employer_id = req_string(body, "employer_id")
    basis_codes = req_enum_array(body, "basis_codes", constants.BASIS_CODES)
    incident_date = req_date(body, "incident_date")
    harm_description = req_string(body, "harm_description")
    employee_count_at_incident = req_int(
        body, "employee_count_at_incident", minimum=0
    )

    # Step 4: existence, body references in declared order.
    complainant = db.complainants.get(complainant_id)
    if complainant is None:
        raise ApiError(
            ERR_COMPLAINANT_NOT_FOUND, "No complainant with the given id."
        )
    employer = db.employers.get(employer_id)
    if employer is None:
        raise ApiError(ERR_EMPLOYER_NOT_FOUND, "No employer with the given id.")

    # Step 5: ownership. A ChargingParty files as itself.
    if role == constants.ROLE_CHARGING_PARTY and complainant_id != user_id:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            "ChargingParty must file with complainant_id == X-User-ID.",
        )

    # Step 9 (business-temporal): incident_date must not be after the clock.
    if incident_date > today():
        raise ApiError(
            ERR_INCIDENT_DATE_FUTURE,
            "incident_date is after the current logical clock.",
        )

    # Synchronous jurisdictional screening (never rejects on size/lateness).
    agency = screening.match_agency(employer["state_code"])
    screened = screening.run_screening(
        basis_codes=basis_codes,
        incident_date=incident_date,
        received_date=today(),
        employee_count_at_incident=employee_count_at_incident,
        agency=agency,
    )

    charge = {
        **common_fields(),
        "complainant_id": complainant_id,
        "employer_id": employer_id,
        "deferral_agency_id": screened["deferral_agency_id"],
        "basis_codes": basis_codes,
        "covered_bases": screened["covered_bases"],
        "incident_date": incident_date,
        "harm_description": harm_description,
        "employee_count_at_incident": employee_count_at_incident,
        "received_date": today(),
        "case_status": screened["case_status"],
        "disclosure_hold": constants.HOLD_NONE,
        "jurisdiction_outcome": screened["jurisdiction_outcome"],
        "filing_deadline_date": screened["filing_deadline_date"],
        "investigation_owner": screened["investigation_owner"],
        "dual_filed": screened["dual_filed"],
        "investigation_case_id": None,
        "priority_escalated": False,
        "settled_amount_cents": 0,
        "settled_via": None,
        "settled_at": None,
        "systemic_case_id": None,
    }
    db.charges[charge["id"]] = charge
    return respond_object(serializers.serialize_charge(charge), status=201)


@bp.get("/charges")
def list_charges():
    _, role = authenticate()
    require_roles(role, _LIST_ROLES)

    status = _arg("status")
    employer_id = _arg("employer_id")
    complainant_id = _arg("complainant_id")
    deferral_agency_id = _arg("deferral_agency_id")
    systemic_case_id = _arg("systemic_case_id")
    basis = _arg("basis")

    rows = list(db.charges.values())
    if role == constants.ROLE_STATE_AGENCY_OFFICER:
        rows = [
            c for c in rows if c["investigation_owner"] == constants.OWNER_FEPA
        ]
    if status is not None:
        rows = [c for c in rows if c["case_status"] == status]
    if employer_id is not None:
        rows = [c for c in rows if c["employer_id"] == employer_id]
    if complainant_id is not None:
        rows = [c for c in rows if c["complainant_id"] == complainant_id]
    if deferral_agency_id is not None:
        rows = [c for c in rows if c["deferral_agency_id"] == deferral_agency_id]
    if systemic_case_id is not None:
        rows = [c for c in rows if c["systemic_case_id"] == systemic_case_id]
    if basis is not None:
        rows = [c for c in rows if basis in c["basis_codes"]]
    return paginate_and_respond(rows, serializers.serialize_charge)


def _arg(name):
    from flask import request

    value = request.args.get(name)
    return value if value != "" else None


@bp.get("/charges/<charge_id>")
def get_charge(charge_id):
    user_id, role = authenticate()
    require_roles(role, _DETAIL_ROLES)
    charge = get_charge_or_404(charge_id)
    check_party_ownership(user_id, role, charge)

    # Confidentiality: SEALED charges reject non-privileged roles; privileged
    # reads auto-append an INTERNAL_ACCESS DisclosureRecord.
    if charge["disclosure_hold"] == constants.HOLD_SEALED:
        if role not in constants.SEALED_PRIVILEGED_ROLES:
            raise ApiError(
                ERR_CONFIDENTIALITY_SEALED,
                "Charge is sealed and the role is not privileged.",
            )
        cascades.record_disclosure(
            charge,
            accessor_role=role,
            accessor_user_id=user_id,
            legal_basis=constants.DISCLOSURE_INTERNAL_ACCESS,
            target_description=None,
        )

    return respond_object(serializers.serialize_charge(charge), status=200)


@bp.post("/charges/<charge_id>/amend")
def amend_charge(charge_id):
    user_id, role = authenticate()
    require_roles(role, (constants.ROLE_CHARGING_PARTY,))
    # Step 3: schema (expected_charge_version is non-optional per PRD 2.7).
    body = request_body()
    expected_version = req_int(body, "expected_charge_version")
    basis_codes, has_basis = opt_enum_array(
        body, "basis_codes", constants.BASIS_CODES
    )
    incident_date, has_incident = opt_date(body, "incident_date")
    harm_description, has_harm = opt_string(body, "harm_description")

    # Step 4: existence.
    charge = get_charge_or_404(charge_id)
    # Step 5: ownership.
    if user_id != charge["complainant_id"]:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            "ChargingParty may only amend its own charges.",
        )
    # Step 6: state. Terminal charge reports its closedness; amendment is
    # blocked in DETERMINATION_REVIEW, CONCILIATION, CLOSED_SETTLED, and
    # LITIGATION_REFERRED with the generic state error.
    if charge["case_status"] in constants.CHARGE_TERMINAL_STATES:
        raise ApiError(ERR_CHARGE_ALREADY_CLOSED, "Charge is in a terminal state.")
    if charge["case_status"] not in constants.CHARGE_WORKABLE_STATES:
        raise ApiError(
            ERR_INVALID_STATE,
            "Charge in %s cannot be amended." % charge["case_status"],
        )
    # Step 9 (business-temporal): the amended incident date must not be in
    # the future relative to the logical clock.
    if has_incident and incident_date > today():
        raise ApiError(
            ERR_INCIDENT_DATE_FUTURE,
            "incident_date is after the current logical clock.",
        )
    # Step 10: optimistic concurrency.
    if expected_version != charge["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_charge_version does not match the charge's current version.",
        )

    if has_basis:
        charge["basis_codes"] = basis_codes
    if has_incident:
        charge["incident_date"] = incident_date
    if has_harm:
        charge["harm_description"] = harm_description

    # Amending incident_date re-runs the full screening against the
    # recomputed deadline; a basis change re-derives covered_bases through
    # the same pinned size screen.
    if has_basis or has_incident:
        agency = (
            db.deferral_agencies.get(charge["deferral_agency_id"])
            if charge["deferral_agency_id"]
            else None
        )
        screened = screening.run_screening(
            basis_codes=charge["basis_codes"],
            incident_date=charge["incident_date"],
            received_date=charge["received_date"],
            employee_count_at_incident=charge["employee_count_at_incident"],
            agency=agency,
        )
        charge["covered_bases"] = screened["covered_bases"]
        charge["filing_deadline_date"] = screened["filing_deadline_date"]
        charge["jurisdiction_outcome"] = screened["jurisdiction_outcome"]
        if screened["jurisdiction_outcome"] in (
            constants.JURISDICTION_DISMISSED_UNTIMELY,
            constants.JURISDICTION_DISMISSED_NO_JURISDICTION,
        ):
            run_dismissal_cascade(charge, screened["jurisdiction_outcome"])

    bump(charge)
    return respond_object(serializers.serialize_charge(charge), status=200)


@bp.post("/charges/<charge_id>/withdraw")
def withdraw_charge(charge_id):
    user_id, role = authenticate()
    require_roles(role, (constants.ROLE_CHARGING_PARTY,))
    request_body(required=False)
    charge = get_charge_or_404(charge_id)
    if user_id != charge["complainant_id"]:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            "ChargingParty may only withdraw its own charges.",
        )
    if charge["case_status"] in constants.CHARGE_TERMINAL_STATES:
        raise ApiError(ERR_CHARGE_ALREADY_CLOSED, "Charge is in a terminal state.")
    if charge["case_status"] not in constants.CHARGE_WORKABLE_STATES:
        raise ApiError(
            ERR_INVALID_STATE,
            "Charge in %s cannot be withdrawn." % charge["case_status"],
        )

    # Withdraw cascade, shaped by the state left behind (PRD 3.3): open
    # mediations are DECLINED with their SCHEDULED sessions CANCELLED, and a
    # live investigation (OPEN/GATHERING/SUSPENDED_MEDIATION) is CLOSED with
    # its open requests WAIVED. DELEGATED_TO_FEPA changes the status only.
    cascades.decline_open_mediations(charge)
    investigation = cascades.investigation_for_charge(charge)
    if investigation is not None:
        cascades.close_investigation(investigation)

    charge["case_status"] = constants.CHARGE_WITHDRAWN
    bump(charge)
    cascades.reeval_systemic_for_charge(charge)
    return respond_object(serializers.serialize_charge(charge), status=200)
