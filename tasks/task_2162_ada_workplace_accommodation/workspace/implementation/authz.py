"""Rejection ladder steps 1-4, 8, 9 and 12 (PRD 2.1 / 2.6 / 2.10)."""
import functools

from flask import g, request

from envelope import error_response
from errors import ApiError
from store import store

ROLES = (
    "Employee",
    "Manager",
    "AccommodationCoordinator",
    "MedicalReviewOfficer",
    "FinanceOfficer",
    "AppealOfficer",
    "ComplianceAuditor",
)
ALL_ROLES = list(ROLES)
ENTITY_BACKED = ("Employee", "Manager")

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def authenticate(endpoint_roles):
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    # 1. headers present and role recognised
    if user_id is None or role is None or user_id == "" or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    g.actor = None
    # 2. entity-backed actor resolves
    endpoint_has_entity_backed = any(r in endpoint_roles for r in ENTITY_BACKED)
    if endpoint_has_entity_backed and role in ENTITY_BACKED:
        actor = store.employees.get(user_id)
        if actor is None:
            raise ApiError("ERR_UNKNOWN_ACTOR")
        g.actor = actor
    # 3. role permitted on this endpoint
    if role not in endpoint_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    # 4. people-manager flag
    if "Manager" in endpoint_roles and role == "Manager":
        if not g.actor.get("is_people_manager"):
            raise ApiError("ERR_NOT_A_PEOPLE_MANAGER")


def endpoint(roles):
    """Wrap a view with ladder steps 1-4 and uniform error rendering."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                authenticate(roles)
                return fn(*args, **kwargs)
            except ApiError as err:
                return error_response(err)
        return wrapper
    return decorator


# --- ladder step 8: case ownership for employees -------------------------
def require_case_owner(req):
    if g.role == "Employee" and g.user_id != req["employee_id"]:
        raise ApiError("ERR_NOT_CASE_OWNER")


def require_case_owner_id(employee_id):
    if g.role == "Employee" and g.user_id != employee_id:
        raise ApiError("ERR_NOT_CASE_OWNER")


# --- ladder step 9: manager department scope -----------------------------
def require_manager_scope_case(req):
    if g.role != "Manager":
        return
    employee = store.employees.get(req["employee_id"])
    target_dept = employee["department_code"] if employee else None
    if g.actor["department_code"] != target_dept:
        raise ApiError("ERR_MANAGER_SCOPE_VIOLATION")


def require_manager_scope_department(department_code):
    if g.role != "Manager":
        return
    if g.actor["department_code"] != department_code:
        raise ApiError("ERR_MANAGER_SCOPE_VIOLATION")


# --- ladder step 12: the case seal ---------------------------------------
def require_not_sealed(req):
    if req["confidentiality_posture"] == "SEALED":
        raise ApiError("ERR_CASE_SEALED")


# --- ladder step 6/7: existence lookups ----------------------------------
def _need(collection, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def need_employee(row_id):
    return _need(store.employees, row_id, "ERR_EMPLOYEE_NOT_FOUND")


def need_profile(row_id):
    return _need(store.job_profiles, row_id, "ERR_JOB_PROFILE_NOT_FOUND")


def need_function(row_id):
    return _need(store.essential_functions, row_id, "ERR_ESSENTIAL_FUNCTION_NOT_FOUND")


def need_request(row_id):
    return _need(store.requests, row_id, "ERR_REQUEST_NOT_FOUND")


def need_doc_request(row_id):
    return _need(store.doc_requests, row_id, "ERR_DOC_REQUEST_NOT_FOUND")


def need_analysis(row_id):
    return _need(store.function_analyses, row_id, "ERR_FUNCTION_ANALYSIS_NOT_FOUND")


def need_option(row_id):
    return _need(store.options, row_id, "ERR_OPTION_NOT_FOUND")


def need_trial(row_id):
    return _need(store.trials, row_id, "ERR_TRIAL_NOT_FOUND")


def need_denial(row_id):
    return _need(store.denials, row_id, "ERR_DENIAL_NOT_FOUND")


def need_appeal(row_id):
    return _need(store.appeals, row_id, "ERR_APPEAL_NOT_FOUND")


def need_absence(row_id):
    return _need(store.absences, row_id, "ERR_ABSENCE_RECORD_NOT_FOUND")
