"""Applications: create an eligibility case and drive its state machine."""
from flask import Blueprint

from auth import authenticate, require_role
from db import STORE, new_record, bump
from envelope import ok_object
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_APPLICATION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_FORBIDDEN_ROLE,
)
from helpers import (
    get_body,
    raw_body,
    check_unknown,
    as_str,
    as_int,
    as_enum,
    as_list_enum,
    invalid,
)
import domain
import serializers

bp = Blueprint("applications", __name__)

BARRIER_CODES = {
    "FOSTER_CARE",
    "HOMELESS",
    "SINGLE_PARENT",
    "DISABILITY",
    "OFFENDER",
    "LOW_BASIC_SKILLS",
}

REVIEW_ACTIONS = {"begin_review", "request_info", "determine"}  # EligibilityReviewer
COUNSELOR_ACTIONS = {"provide_info", "appeal"}  # AdmissionsCounselor
ALL_ACTIONS = REVIEW_ACTIONS | COUNSELOR_ACTIONS


@bp.route("/jc/applications", methods=["POST"])
def create_application():
    user_id, role = authenticate()
    require_role(role, {"AdmissionsCounselor"})
    body = get_body()
    check_unknown(
        body,
        {
            "applicant_id",
            "household_size",
            "annual_income_cents",
            "barrier_flags",
            "expected_applicant_version",
        },
    )
    applicant_id = as_str(body, "applicant_id", required=True)
    household_size = as_int(body, "household_size", required=True, lo=1, hi=domain.HOUSEHOLD_SIZE_MAX)
    annual_income_cents = as_int(body, "annual_income_cents", required=True, lo=0)
    barrier_flags = as_list_enum(body, "barrier_flags", BARRIER_CODES, required=True)
    expected_version = as_int(body, "expected_applicant_version", required=True)
    applicant = STORE.applicants.get(applicant_id)
    if applicant is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Applicant not found")
    # Priority 6: OCC on the applicant.
    if expected_version != applicant["version"]:
        raise ApiError(
            ERR_STALE_VERSION[0],
            ERR_STALE_VERSION[1],
            "expected_applicant_version does not match the applicant's current version",
        )
    # Priority 11: only one open case per applicant.
    open_case = any(
        ap["applicant_id"] == applicant["id"] and ap["status"] in domain.APPLICATION_NONTERMINAL
        for ap in STORE.applications.values()
    )
    if open_case:
        raise ApiError(
            ERR_DUPLICATE_APPLICATION[0],
            ERR_DUPLICATE_APPLICATION[1],
            "Applicant already has a non-terminal application",
        )
    rec = new_record()
    rec.update(
        {
            "applicant_id": applicant["id"],
            "intake_counselor_id": user_id,
            "reviewer_id": None,
            "household_size": household_size,
            "annual_income_cents": annual_income_cents,
            "barrier_flags": barrier_flags,
            "status": "SUBMITTED",
            "determination_reasons": [],
            "determined_at": None,
        }
    )
    STORE.applications[rec["id"]] = rec
    bump(applicant)
    return ok_object(serializers.application_view(rec), status=201)


def _overwrite_snapshot(application, body):
    """provide_info / appeal: supplied snapshot fields overwrite stored ones."""
    if "annual_income_cents" in body:
        application["annual_income_cents"] = as_int(body, "annual_income_cents", lo=0)
    if "household_size" in body:
        application["household_size"] = as_int(
            body, "household_size", lo=1, hi=domain.HOUSEHOLD_SIZE_MAX
        )
    if "barrier_flags" in body:
        application["barrier_flags"] = as_list_enum(body, "barrier_flags", BARRIER_CODES)


@bp.route("/jc/applications/<application_id>/transition", methods=["POST"])
def application_transition(application_id):
    user_id, role = authenticate()
    require_role(role, {"AdmissionsCounselor", "EligibilityReviewer"})
    # Action-level role fit (RBAC matrix) and segregation of duties are
    # evaluated before full body validation, so peek at the raw action.
    raw = raw_body() or {}
    action = raw.get("action")
    if isinstance(action, str) and action in ALL_ACTIONS:
        needed = "EligibilityReviewer" if action in REVIEW_ACTIONS else "AdmissionsCounselor"
        if role != needed:
            raise ApiError(
                ERR_FORBIDDEN_ROLE[0],
                ERR_FORBIDDEN_ROLE[1],
                "Role {} may not perform action {}".format(role, action),
            )
    application = STORE.applications.get(application_id)
    if application is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Application not found")
    # Priority 3: segregation of duties on review actions.
    if action in REVIEW_ACTIONS and user_id == application["intake_counselor_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES[0],
            ERR_SEGREGATION_OF_DUTIES[1],
            "The intake counselor may not review this application",
        )
    # Priority 5: full body validation.
    body = get_body()
    check_unknown(
        body,
        {"action", "annual_income_cents", "household_size", "barrier_flags", "info_request_note"},
    )
    action = as_enum(body, "action", sorted(ALL_ACTIONS), required=True)
    if "info_request_note" in body:
        as_str(body, "info_request_note")
    if action in ("provide_info", "appeal"):
        if "annual_income_cents" in body:
            as_int(body, "annual_income_cents", lo=0)
        if "household_size" in body:
            as_int(body, "household_size", lo=1, hi=domain.HOUSEHOLD_SIZE_MAX)
        if "barrier_flags" in body:
            as_list_enum(body, "barrier_flags", BARRIER_CODES)
    # Priority 7: ELIGIBLE is terminal.
    if application["status"] == "ELIGIBLE":
        raise ApiError(
            ERR_ALREADY_TERMINAL[0],
            ERR_ALREADY_TERMINAL[1],
            "Application is ELIGIBLE (terminal)",
        )
    status = application["status"]
    if action == "begin_review":
        if status != "SUBMITTED":
            _invalid_state(action, status)
        application["status"] = "UNDER_REVIEW"
        application["reviewer_id"] = user_id
    elif action == "request_info":
        if status != "UNDER_REVIEW":
            _invalid_state(action, status)
        application["status"] = "INFO_REQUESTED"
    elif action == "provide_info":
        if status != "INFO_REQUESTED":
            _invalid_state(action, status)
        _overwrite_snapshot(application, body)
        application["status"] = "UNDER_REVIEW"
    elif action == "appeal":
        if status != "INELIGIBLE":
            _invalid_state(action, status)
        _overwrite_snapshot(application, body)
        application["status"] = "UNDER_REVIEW"
    elif action == "determine":
        if status != "UNDER_REVIEW":
            _invalid_state(action, status)
        applicant = STORE.applicants[application["applicant_id"]]
        domain.run_determination(application, applicant)
    bump(application)
    return ok_object(serializers.application_view(application), status=200)


def _invalid_state(action, status):
    raise ApiError(
        ERR_INVALID_STATE[0],
        ERR_INVALID_STATE[1],
        "Action {} is not defined from state {}".format(action, status),
    )
