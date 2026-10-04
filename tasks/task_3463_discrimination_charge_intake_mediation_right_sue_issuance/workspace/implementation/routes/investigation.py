"""Investigation: case reads, assignment, evidence requests, interviews
(PRD 3.5)."""

from datetime import timedelta
from flask import Blueprint, request

import constants
import serializers
from domain import cascades, priority
from errors import (
    ApiError,
    ERR_CHARGE_ALREADY_CLOSED,
    ERR_EVIDENCE_REQUEST_NOT_FOUND,
    ERR_INTERVIEW_BUFFER_CONFLICT,
    ERR_INVALID_STATE,
    ERR_INVESTIGATION_CASE_NOT_FOUND,
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
from validation import req_datetime, req_enum, req_string

bp = Blueprint("investigation", __name__, url_prefix="/eeoc")

_CASE_READ_ROLES = (
    constants.ROLE_INVESTIGATOR,
    constants.ROLE_DIRECTOR,
    constants.ROLE_COMMISSIONER,
)

_EVIDENCE_LIST_ROLES = (
    constants.ROLE_INVESTIGATOR,
    constants.ROLE_DIRECTOR,
    constants.ROLE_COMMISSIONER,
    constants.ROLE_RESPONDENT_REP,
)

_INTERVIEW_LIST_ROLES = (
    constants.ROLE_INVESTIGATOR,
    constants.ROLE_DIRECTOR,
)


def get_investigation_or_404(investigation_id):
    investigation = db.investigation_cases.get(investigation_id)
    if investigation is None:
        raise ApiError(
            ERR_INVESTIGATION_CASE_NOT_FOUND,
            "No investigation case with the given id.",
        )
    return investigation


def charge_of_investigation(investigation):
    return db.charges[investigation["charge_id"]]


def require_assigned_investigator(user_id, investigation):
    """Only the assigned investigator may write to the case."""
    if (
        investigation["assigned_investigator_id"] is None
        or user_id != investigation["assigned_investigator_id"]
    ):
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            "Only the assigned investigator may write to this case.",
        )


@bp.get("/investigation-cases/<investigation_id>")
def get_investigation(investigation_id):
    _, role = authenticate()
    require_roles(role, _CASE_READ_ROLES)
    investigation = get_investigation_or_404(investigation_id)
    priority.refresh_investigation(investigation)
    return respond_object(
        serializers.serialize_investigation_case(investigation), status=200
    )


@bp.get("/investigation-cases")
def list_investigations():
    _, role = authenticate()
    require_roles(role, _CASE_READ_ROLES)
    charge_id = request.args.get("charge_id") or None
    status = request.args.get("status") or None
    assignee = request.args.get("assigned_investigator_id") or None

    rows = list(db.investigation_cases.values())
    if charge_id is not None:
        rows = [i for i in rows if i["charge_id"] == charge_id]
    if status is not None:
        rows = [i for i in rows if i["status"] == status]
    if assignee is not None:
        rows = [i for i in rows if i["assigned_investigator_id"] == assignee]
    for investigation in rows:
        priority.refresh_investigation(investigation)
    return paginate_and_respond(rows, serializers.serialize_investigation_case)


@bp.post("/investigation-cases/<investigation_id>/assign")
def assign_investigator(investigation_id):
    _, role = authenticate()
    require_roles(role, (constants.ROLE_DIRECTOR,))
    body = request_body()
    investigator_user_id = req_string(body, "investigator_user_id")

    investigation = get_investigation_or_404(investigation_id)

    # Segregation of duties across the mediation firewall: the target must
    # never have served as mediator on any session of the same charge.
    charge = charge_of_investigation(investigation)
    for mediation in cascades.mediations_for_charge(charge):
        for session in cascades.sessions_for_mediation(mediation):
            if session["mediator_user_id"] == investigator_user_id:
                raise ApiError(
                    ERR_SEGREGATION_OF_DUTIES,
                    "Assignee previously mediated this charge.",
                )

    investigation["assigned_investigator_id"] = investigator_user_id
    bump(investigation)
    priority.refresh_investigation(investigation)
    return respond_object(
        serializers.serialize_investigation_case(investigation), status=200
    )


@bp.post("/investigation-cases/<investigation_id>/evidence-requests")
def create_evidence_request(investigation_id):
    user_id, role = authenticate()
    require_roles(role, (constants.ROLE_INVESTIGATOR,))
    body = request_body()
    request_type = req_enum(
        body, "request_type", constants.EVIDENCE_REQUEST_TYPES
    )

    investigation = get_investigation_or_404(investigation_id)
    require_assigned_investigator(user_id, investigation)
    charge = charge_of_investigation(investigation)
    if charge["case_status"] in constants.CHARGE_TERMINAL_STATES:
        raise ApiError(ERR_CHARGE_ALREADY_CLOSED, "Charge is in a terminal state.")
    if investigation["status"] not in (
        constants.INVESTIGATION_OPEN,
        constants.INVESTIGATION_GATHERING,
    ):
        raise ApiError(
            ERR_INVALID_STATE,
            "Evidence requests require an OPEN or GATHERING case.",
        )

    issued = today()
    request_row = {
        **common_fields(),
        "investigation_case_id": investigation["id"],
        "request_type": request_type,
        "issued_date": issued,
        "due_date": issued + timedelta(days=constants.EVIDENCE_RESPONSE_WINDOW_DAYS),
        "status": constants.EVIDENCE_PENDING,
        "response_text": None,
        "responded_late": False,
    }
    db.evidence_requests[request_row["id"]] = request_row

    # First evidence activity moves the case OPEN -> GATHERING.
    if investigation["status"] == constants.INVESTIGATION_OPEN:
        investigation["status"] = constants.INVESTIGATION_GATHERING
        bump(investigation)
    priority.refresh_investigation(investigation)
    return respond_object(
        serializers.serialize_evidence_request(request_row), status=201
    )


@bp.get("/investigation-cases/<investigation_id>/evidence-requests")
def list_evidence_requests(investigation_id):
    user_id, role = authenticate()
    require_roles(role, _EVIDENCE_LIST_ROLES)
    investigation = get_investigation_or_404(investigation_id)
    charge = charge_of_investigation(investigation)
    # RespondentRep sees only requests directed at its own employer.
    if role == constants.ROLE_RESPONDENT_REP and user_id != charge["employer_id"]:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            "RespondentRep sees only requests against its own employer.",
        )
    priority.refresh_investigation(investigation)  # applies lazy OVERDUE
    rows = cascades.requests_for_investigation(investigation)
    return paginate_and_respond(rows, serializers.serialize_evidence_request)


@bp.post("/evidence-requests/<request_id>/respond")
def respond_evidence_request(request_id):
    user_id, role = authenticate()
    require_roles(role, (constants.ROLE_RESPONDENT_REP,))
    body = request_body()
    response_text = req_string(body, "response_text")

    request_row = db.evidence_requests.get(request_id)
    if request_row is None:
        raise ApiError(
            ERR_EVIDENCE_REQUEST_NOT_FOUND,
            "No evidence request with the given id.",
        )
    investigation = db.investigation_cases[request_row["investigation_case_id"]]
    charge = charge_of_investigation(investigation)

    # Ownership: the response comes from the charge's respondent employer.
    if user_id != charge["employer_id"]:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            "RespondentRep may only respond for its own employer.",
        )

    # Evaluate the lazy OVERDUE transition first so a late response is
    # flagged correctly.
    priority.refresh_evidence_request(request_row)
    if request_row["status"] not in (
        constants.EVIDENCE_PENDING,
        constants.EVIDENCE_OVERDUE,
    ):
        raise ApiError(
            ERR_INVALID_STATE,
            "Evidence request in %s cannot be responded to."
            % request_row["status"],
        )

    request_row["responded_late"] = (
        request_row["status"] == constants.EVIDENCE_OVERDUE
    )
    request_row["status"] = constants.EVIDENCE_RESPONDED
    request_row["response_text"] = response_text
    bump(request_row)
    priority.refresh_investigation(investigation)
    return respond_object(
        serializers.serialize_evidence_request(request_row), status=200
    )


@bp.post("/investigation-cases/<investigation_id>/interviews")
def log_interview(investigation_id):
    user_id, role = authenticate()
    require_roles(role, (constants.ROLE_INVESTIGATOR,))
    body = request_body()
    witness_name = req_string(body, "witness_name")
    interview_start = req_datetime(body, "interview_start")
    interview_end = req_datetime(body, "interview_end")
    summary = req_string(body, "summary")
    if interview_end <= interview_start:
        raise ApiError(
            ERR_VALIDATION_FAILED,
            "interview_end must be strictly after interview_start.",
        )

    investigation = get_investigation_or_404(investigation_id)
    require_assigned_investigator(user_id, investigation)
    charge = charge_of_investigation(investigation)
    if charge["case_status"] in constants.CHARGE_TERMINAL_STATES:
        raise ApiError(ERR_CHARGE_ALREADY_CLOSED, "Charge is in a terminal state.")
    if investigation["status"] == constants.INVESTIGATION_CLOSED:
        raise ApiError(
            ERR_INVALID_STATE, "Cannot log interviews on a CLOSED case."
        )

    # 30-minute buffer on BOTH sides, across ALL of this investigator's
    # interviews regardless of case. Interviews may be in the past.
    buffer = timedelta(minutes=constants.INTERVIEW_BUFFER_MINUTES)
    for other in db.witness_interviews.values():
        if other["investigator_user_id"] != user_id:
            continue
        if (
            interview_start < other["interview_end"] + buffer
            and other["interview_start"] < interview_end + buffer
        ):
            raise ApiError(
                ERR_INTERVIEW_BUFFER_CONFLICT,
                "Interview leaves less than a %d-minute gap to another "
                "interview of this investigator."
                % constants.INTERVIEW_BUFFER_MINUTES,
            )

    interview = {
        **common_fields(),
        "investigation_case_id": investigation["id"],
        "investigator_user_id": user_id,
        "witness_name": witness_name,
        "interview_start": interview_start,
        "interview_end": interview_end,
        "summary": summary,
    }
    db.witness_interviews[interview["id"]] = interview

    # First evidence activity moves the case OPEN -> GATHERING.
    if investigation["status"] == constants.INVESTIGATION_OPEN:
        investigation["status"] = constants.INVESTIGATION_GATHERING
        bump(investigation)
    return respond_object(
        serializers.serialize_witness_interview(interview), status=201
    )


@bp.get("/investigation-cases/<investigation_id>/interviews")
def list_interviews(investigation_id):
    _, role = authenticate()
    require_roles(role, _INTERVIEW_LIST_ROLES)
    investigation = get_investigation_or_404(investigation_id)
    rows = [
        i
        for i in db.witness_interviews.values()
        if i["investigation_case_id"] == investigation["id"]
    ]
    return paginate_and_respond(rows, serializers.serialize_witness_interview)
