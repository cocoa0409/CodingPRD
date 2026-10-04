"""Mediation: offers, party responses, sessions, and conclusion (PRD 3.4)."""

from flask import Blueprint

import constants
import serializers
from domain import cascades
from errors import (
    ApiError,
    ERR_CHARGE_ALREADY_CLOSED,
    ERR_INVALID_STATE,
    ERR_MEDIATION_CASE_NOT_FOUND,
    ERR_MEDIATION_ROUND_EXHAUSTED,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SESSION_IN_PAST,
    ERR_SESSION_OVERLAP,
    ERR_VALIDATION_FAILED,
)
from helpers import (
    authenticate,
    bump,
    check_party_ownership,
    common_fields,
    now,
    paginate_and_respond,
    request_body,
    require_roles,
    respond_object,
)
from store import db
from validation import present_non_null, req_datetime, req_enum, req_int
from routes.charges import get_charge_or_404

bp = Blueprint("mediation", __name__, url_prefix="/eeoc")

_MEDIATION_READ_ROLES = (
    constants.ROLE_INTAKE_OFFICER,
    constants.ROLE_MEDIATOR,
    constants.ROLE_DIRECTOR,
    constants.ROLE_COMMISSIONER,
    constants.ROLE_CHARGING_PARTY,
    constants.ROLE_RESPONDENT_REP,
)

_SESSION_LIST_ROLES = (
    constants.ROLE_MEDIATOR,
    constants.ROLE_DIRECTOR,
    constants.ROLE_INTAKE_OFFICER,
    constants.ROLE_CHARGING_PARTY,
    constants.ROLE_RESPONDENT_REP,
)


def get_mediation_or_404(mediation_id):
    mediation = db.mediation_cases.get(mediation_id)
    if mediation is None:
        raise ApiError(
            ERR_MEDIATION_CASE_NOT_FOUND, "No mediation case with the given id."
        )
    return mediation


@bp.post("/charges/<charge_id>/mediation-cases")
def offer_mediation(charge_id):
    _, role = authenticate()
    require_roles(role, (constants.ROLE_INTAKE_OFFICER,))
    request_body(required=False)
    charge = get_charge_or_404(charge_id)

    # State: offer requires DOCKETED or UNDER_INVESTIGATION; every prior
    # mediation case must be terminal.
    if charge["case_status"] in constants.CHARGE_TERMINAL_STATES:
        raise ApiError(ERR_CHARGE_ALREADY_CLOSED, "Charge is in a terminal state.")
    if charge["case_status"] not in (
        constants.CHARGE_DOCKETED,
        constants.CHARGE_UNDER_INVESTIGATION,
    ):
        raise ApiError(
            ERR_INVALID_STATE,
            "Mediation may only be offered from DOCKETED or UNDER_INVESTIGATION.",
        )
    priors = cascades.mediations_for_charge(charge)
    for prior in priors:
        if prior["status"] not in constants.MEDIATION_TERMINAL_STATES:
            raise ApiError(
                ERR_INVALID_STATE,
                "A prior mediation case is still non-terminal.",
            )
    if len(priors) >= constants.MAX_MEDIATION_ROUNDS:
        raise ApiError(
            ERR_MEDIATION_ROUND_EXHAUSTED,
            "The charge has exhausted its %d mediation rounds."
            % constants.MAX_MEDIATION_ROUNDS,
        )

    mediation = {
        **common_fields(),
        "charge_id": charge["id"],
        "round_number": len(priors) + 1,
        "complainant_response": constants.RESPONSE_PENDING,
        "respondent_response": constants.RESPONSE_PENDING,
        "status": constants.MEDIATION_OFFERED,
        "settlement_amount_cents": None,
        "concluded_at": None,
    }
    db.mediation_cases[mediation["id"]] = mediation
    return respond_object(
        serializers.serialize_mediation_case(mediation), status=201
    )


@bp.get("/charges/<charge_id>/mediation-cases")
def list_mediation_cases(charge_id):
    user_id, role = authenticate()
    require_roles(role, _MEDIATION_READ_ROLES)
    charge = get_charge_or_404(charge_id)
    check_party_ownership(user_id, role, charge)
    rows = cascades.mediations_for_charge(charge)
    return paginate_and_respond(rows, serializers.serialize_mediation_case)


@bp.get("/mediation-cases/<mediation_id>")
def get_mediation_case(mediation_id):
    user_id, role = authenticate()
    require_roles(role, _MEDIATION_READ_ROLES)
    mediation = get_mediation_or_404(mediation_id)
    charge = db.charges[mediation["charge_id"]]
    check_party_ownership(user_id, role, charge)
    return respond_object(
        serializers.serialize_mediation_case(mediation), status=200
    )


@bp.post("/mediation-cases/<mediation_id>/respond")
def respond_mediation(mediation_id):
    user_id, role = authenticate()
    require_roles(
        role, (constants.ROLE_CHARGING_PARTY, constants.ROLE_RESPONDENT_REP)
    )
    body = request_body()
    response = req_enum(body, "response", constants.MEDIATION_RESPONSES)

    mediation = get_mediation_or_404(mediation_id)
    charge = db.charges[mediation["charge_id"]]

    # The recorded party is derived from the caller's identity.
    if user_id == charge["complainant_id"]:
        field = "complainant_response"
    elif user_id == charge["employer_id"]:
        field = "respondent_response"
    else:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            "Caller is neither the charge's complainant nor its employer.",
        )

    if mediation["status"] != constants.MEDIATION_OFFERED:
        raise ApiError(
            ERR_INVALID_STATE,
            "Mediation case in %s cannot be responded to." % mediation["status"],
        )
    if mediation[field] != constants.RESPONSE_PENDING:
        raise ApiError(
            ERR_INVALID_STATE, "This party has already responded to the offer."
        )

    mediation[field] = response

    if response == constants.RESPONSE_DECLINED:
        mediation["status"] = constants.MEDIATION_DECLINED
        bump(mediation)
        # A decline on a DOCKETED charge sends it to investigation; a decline
        # of an UNDER_INVESTIGATION re-offer leaves the charge where it is.
        if charge["case_status"] == constants.CHARGE_DOCKETED:
            charge["case_status"] = constants.CHARGE_UNDER_INVESTIGATION
            cascades.auto_create_investigation(charge)
            bump(charge)
    else:
        # Second ACCEPTED activates the mediation and moves the charge.
        both_accepted = (
            mediation["complainant_response"] == constants.RESPONSE_ACCEPTED
            and mediation["respondent_response"] == constants.RESPONSE_ACCEPTED
        )
        if both_accepted:
            mediation["status"] = constants.MEDIATION_ACTIVE
            bump(mediation)
            charge["case_status"] = constants.CHARGE_IN_MEDIATION
            investigation = cascades.investigation_for_charge(charge)
            if (
                investigation is not None
                and investigation["status"] == constants.INVESTIGATION_GATHERING
            ):
                investigation["status"] = constants.INVESTIGATION_SUSPENDED_MEDIATION
                bump(investigation)
            bump(charge)
        else:
            bump(mediation)

    return respond_object(
        serializers.serialize_mediation_case(mediation), status=200
    )


@bp.post("/mediation-cases/<mediation_id>/sessions")
def schedule_session(mediation_id):
    user_id, role = authenticate()
    require_roles(role, (constants.ROLE_MEDIATOR,))
    body = request_body()
    scheduled_start = req_datetime(body, "scheduled_start")
    scheduled_end = req_datetime(body, "scheduled_end")
    if scheduled_end <= scheduled_start:
        raise ApiError(
            ERR_VALIDATION_FAILED,
            "scheduled_end must be strictly after scheduled_start.",
        )

    mediation = get_mediation_or_404(mediation_id)
    if mediation["status"] != constants.MEDIATION_ACTIVE:
        raise ApiError(
            ERR_INVALID_STATE,
            "Sessions may only be scheduled while the mediation is ACTIVE.",
        )

    # Half-open overlap rule across this mediator's SCHEDULED sessions on any
    # mediation case: [start, end) intervals; back-to-back is allowed.
    # Evaluated before the past-start check per the §2.8 priority pipeline
    # (step 8 business constraints precede step 9 business-temporal rules).
    for other in db.mediation_sessions.values():
        if other["mediator_user_id"] != user_id:
            continue
        if other["status"] != constants.SESSION_SCHEDULED:
            continue
        if scheduled_start < other["scheduled_end"] and other["scheduled_start"] < scheduled_end:
            raise ApiError(
                ERR_SESSION_OVERLAP,
                "Session overlaps another scheduled session of this mediator.",
            )

    # Temporal: the start must not be before the current logical clock.
    if scheduled_start < now():
        raise ApiError(
            ERR_SESSION_IN_PAST,
            "scheduled_start is before the current logical clock.",
        )

    session = {
        **common_fields(),
        "mediation_case_id": mediation["id"],
        "mediator_user_id": user_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": constants.SESSION_SCHEDULED,
    }
    db.mediation_sessions[session["id"]] = session
    return respond_object(
        serializers.serialize_mediation_session(session), status=201
    )


@bp.get("/mediation-cases/<mediation_id>/sessions")
def list_sessions(mediation_id):
    user_id, role = authenticate()
    require_roles(role, _SESSION_LIST_ROLES)
    mediation = get_mediation_or_404(mediation_id)
    charge = db.charges[mediation["charge_id"]]
    check_party_ownership(user_id, role, charge)
    rows = cascades.sessions_for_mediation(mediation)
    for session in rows:
        cascades.refresh_session_lazy(session)
    return paginate_and_respond(rows, serializers.serialize_mediation_session)


@bp.post("/mediation-cases/<mediation_id>/conclude")
def conclude_mediation(mediation_id):
    _, role = authenticate()
    require_roles(role, (constants.ROLE_MEDIATOR,))
    body = request_body()
    outcome = req_enum(body, "outcome", constants.CONCLUDE_OUTCOMES)
    if outcome == "SETTLED":
        settlement_amount = req_int(body, "settlement_amount_cents")
        if settlement_amount <= 0:
            raise ApiError(
                ERR_VALIDATION_FAILED,
                "settlement_amount_cents must be > 0 when outcome is SETTLED.",
            )
    else:
        if present_non_null(body, "settlement_amount_cents"):
            raise ApiError(
                ERR_VALIDATION_FAILED,
                "settlement_amount_cents is only allowed when outcome is SETTLED.",
            )
        settlement_amount = None

    mediation = get_mediation_or_404(mediation_id)
    charge = db.charges[mediation["charge_id"]]

    # Cross-entity gate: an ACTIVE mediation orphaned by RTS issuance can no
    # longer conclude (PRD 3.4 pins ERR_INVALID_STATE here).
    if mediation["status"] != constants.MEDIATION_ACTIVE:
        raise ApiError(
            ERR_INVALID_STATE,
            "Mediation case in %s cannot be concluded." % mediation["status"],
        )
    if charge["case_status"] != constants.CHARGE_IN_MEDIATION:
        raise ApiError(
            ERR_INVALID_STATE,
            "Charge in %s is not in mediation." % charge["case_status"],
        )

    cascades.cancel_scheduled_sessions(mediation)
    mediation["concluded_at"] = now()

    if outcome == "SETTLED":
        mediation["status"] = constants.MEDIATION_SETTLED
        mediation["settlement_amount_cents"] = settlement_amount
        charge["settled_amount_cents"] = settlement_amount
        charge["settled_via"] = constants.SETTLED_VIA_MEDIATION
        charge["settled_at"] = now()
        charge["case_status"] = constants.CHARGE_CLOSED_SETTLED
        bump(charge)
        bump(mediation)
        cascades.reeval_systemic_for_charge(charge)
    else:
        mediation["status"] = constants.MEDIATION_IMPASSE
        charge["case_status"] = constants.CHARGE_UNDER_INVESTIGATION
        investigation = cascades.investigation_for_charge(charge)
        if investigation is None:
            cascades.auto_create_investigation(charge)
        elif investigation["status"] == constants.INVESTIGATION_SUSPENDED_MEDIATION:
            investigation["status"] = constants.INVESTIGATION_GATHERING
            bump(investigation)
        bump(charge)
        bump(mediation)

    return respond_object(
        serializers.serialize_mediation_case(mediation), status=200
    )
