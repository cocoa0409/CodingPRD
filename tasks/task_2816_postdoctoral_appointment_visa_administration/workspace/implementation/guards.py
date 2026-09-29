"""Authentication, role authorisation, existence lookups and request-shape checks.

The precedence ladder of PRD section 2.11 is enforced by calling these helpers in
order inside each route handler: authenticate -> existence -> ownership -> shape.
"""
from flask import request

from errors import ApiError
from store import dec, parse_date_str, store

ROLE_OFFICER = "PostdocAffairsOfficer"
ROLE_HR = "HRCompensationApprover"
ROLE_EXPORT = "ExportControlReviewer"
ROLE_ADVISOR = "InternationalScholarAdvisor"
ROLE_MENTOR = "FacultyMentor"
ROLE_POSTDOC = "Postdoc"

ALL_ROLES = (ROLE_OFFICER, ROLE_HR, ROLE_EXPORT, ROLE_ADVISOR, ROLE_MENTOR, ROLE_POSTDOC)
ROLE_SET = set(ALL_ROLES)


def authenticate(allowed_roles):
    """Rules 1 and 2 of the ladder."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLE_SET:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return user_id, role


# --------------------------------------------------------------------------
# existence (rule 3)
# --------------------------------------------------------------------------

_COLLECTIONS = {
    "postdoc": ("postdocs", "ERR_POSTDOC_NOT_FOUND"),
    "mentor": ("mentors", "ERR_MENTOR_NOT_FOUND"),
    "funding_source": ("funding_sources", "ERR_FUNDING_SOURCE_NOT_FOUND"),
    "laboratory": ("laboratories", "ERR_LABORATORY_NOT_FOUND"),
    "appointment": ("appointments", "ERR_APPOINTMENT_NOT_FOUND"),
    "visa_case": ("visa_cases", "ERR_VISA_CASE_NOT_FOUND"),
    "development_document": ("development_documents", "ERR_DEVELOPMENT_DOCUMENT_NOT_FOUND"),
    "export_control_review": ("export_control_reviews", "ERR_EXPORT_REVIEW_NOT_FOUND"),
    "lab_access_grant": ("lab_access_grants", "ERR_LAB_GRANT_NOT_FOUND"),
    "reappointment_review": ("reappointment_reviews", "ERR_REAPPOINTMENT_REVIEW_NOT_FOUND"),
    "grievance": ("grievances", "ERR_GRIEVANCE_NOT_FOUND"),
    "exit_record": ("exit_records", "ERR_EXIT_RECORD_NOT_FOUND"),
}


def lookup(kind, record_id):
    collection_name, error_id = _COLLECTIONS[kind]
    collection = getattr(store, collection_name)
    record = collection.get(record_id) if isinstance(record_id, str) else None
    if record is None:
        raise ApiError(error_id, "The referenced %s does not exist." % kind.replace("_", " "))
    return record


def lookup_fk(body, field, kind):
    """Existence check for a body foreign key.

    A field that is absent or null is left for the request-shape rule; a field
    that carries an unresolvable value is a 404 before any shape check runs.
    """
    if not isinstance(body, dict) or field not in body:
        return None
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    return lookup(kind, value)


# --------------------------------------------------------------------------
# request shape (rule 5)
# --------------------------------------------------------------------------

def json_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def need_string(body, field, max_length=None, allow_empty=False):
    value = body.get(field)
    if value is None or not isinstance(value, str):
        bad("%s is required and must be a string." % field)
    if not allow_empty and value.strip() == "":
        bad("%s may not be empty." % field)
    if max_length is not None and len(value) > max_length:
        bad("%s may not exceed %d characters." % (field, max_length))
    return value


def opt_string(body, field, default=None, max_length=None):
    if field not in body or body.get(field) is None:
        return default
    return need_string(body, field, max_length=max_length, allow_empty=True)


def need_enum(body, field, allowed):
    value = body.get(field)
    if value is None or not isinstance(value, str):
        bad("%s is required." % field)
    if value not in allowed:
        bad("%s must be one of %s." % (field, ", ".join(sorted(allowed))))
    return value


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return need_enum(body, field, allowed)


def need_date(body, field):
    value = body.get(field)
    if value is None or not isinstance(value, str):
        bad("%s is required and must be an ISO 8601 date." % field)
    parsed = parse_date_str(value)
    if parsed is None:
        bad("%s must be an ISO 8601 date (YYYY-MM-DD)." % field)
    return parsed


def need_bool(body, field):
    value = body.get(field)
    if not isinstance(value, bool):
        bad("%s must be a boolean." % field)
    return value


def opt_bool(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    return need_bool(body, field)


def need_int(body, field, minimum=None, maximum=None):
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            bad("%s is required and must be an integer." % field)
    if minimum is not None and value < minimum:
        bad("%s may not be smaller than %d." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("%s may not be larger than %d." % (field, maximum))
    return value


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return need_int(body, field, minimum=minimum, maximum=maximum)


def need_amount(body, field, positive=False):
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad("%s is required and must be a number." % field)
    try:
        amount = dec(value)
    except Exception:
        bad("%s must be a number." % field)
    if amount != amount or amount.is_infinite():
        bad("%s must be a finite number." % field)
    if amount < 0:
        bad("%s may not be negative." % field)
    if positive and amount == 0:
        bad("%s must be greater than zero." % field)
    return amount
