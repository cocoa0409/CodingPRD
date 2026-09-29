"""Validation ladder bands 1-5 (PRD 2.6, 2.7) plus pagination and filters."""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import D

ROLES = (
    "Registrar",
    "AcademicAdvisor",
    "CertificationOfficer",
    "LearningSpecialist",
    "Instructor",
    "AppealsCommittee",
    "ComplianceOfficer",
    "AthleticsOperations",
    "Tutor",
    "StudentAthlete",
)

ALL_ROLES = list(ROLES)


def bad_request(message="The request body or query parameters are malformed."):
    return ApiError("ERR_INVALID_REQUEST", message)


# ------------------------------------------------------- bands 1 and 2: auth
def authenticate(allowed_roles):
    """Band 1 then band 2. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return user_id, role


# ------------------------------------------------------------ band 5: bodies
def json_body(required=True):
    """Parse the request body as a JSON object."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        if required:
            raise bad_request("A JSON object body is required.")
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise bad_request("The request body is not valid JSON.")
    if body is None or not isinstance(body, dict):
        raise bad_request("The request body must be a JSON object.")
    return body


def present(body, name):
    return name in body and body[name] is not None


def want_string(body, name, required=True, default=None, allow_empty=False):
    if not present(body, name):
        if required:
            raise bad_request("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        raise bad_request("Field '%s' may not be empty." % name)
    return value


def want_enum(body, name, allowed, required=True, default=None):
    value = want_string(body, name, required=required, default=None)
    if value is None:
        return default
    if value not in allowed:
        raise bad_request(
            "Field '%s' must be one of: %s." % (name, ", ".join(sorted(allowed)))
        )
    return value


def want_bool(body, name, required=False, default=None):
    if not present(body, name):
        if required:
            raise bad_request("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % name)
    return value


def want_int(body, name, required=True, default=None, minimum=None, maximum=None):
    if not present(body, name):
        if required:
            raise bad_request("Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            raise bad_request("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' may not be smaller than %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' may not be larger than %s." % (name, maximum))
    return value


def want_decimal(body, name, required=True, default=None, minimum=None, maximum=None):
    if not present(body, name):
        if required:
            raise bad_request("Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise bad_request("Field '%s' must be a number." % name)
    try:
        number = D(value)
    except (InvalidOperation, ValueError, ArithmeticError):
        raise bad_request("Field '%s' must be a number." % name)
    if number != number or number.is_infinite():
        raise bad_request("Field '%s' must be a finite number." % name)
    if minimum is not None and number < D(minimum):
        raise bad_request("Field '%s' may not be smaller than %s." % (name, minimum))
    if maximum is not None and number > D(maximum):
        raise bad_request("Field '%s' may not be larger than %s." % (name, maximum))
    return number


def want_string_list(body, name, required=False, default=None):
    if not present(body, name):
        if required:
            raise bad_request("Field '%s' is required." % name)
        return list(default) if default is not None else None
    value = body[name]
    if not isinstance(value, list):
        raise bad_request("Field '%s' must be an array of strings." % name)
    out = []
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            raise bad_request("Field '%s' must contain non-empty strings." % name)
        out.append(item)
    return out


def want_int_list(body, name, required=False, default=None, minimum=None, maximum=None):
    if not present(body, name):
        if required:
            raise bad_request("Field '%s' is required." % name)
        return list(default) if default is not None else None
    value = body[name]
    if not isinstance(value, list):
        raise bad_request("Field '%s' must be an array of integers." % name)
    out = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise bad_request("Field '%s' must contain integers." % name)
        if minimum is not None and item < minimum:
            raise bad_request("Field '%s' contains an out-of-range value." % name)
        if maximum is not None and item > maximum:
            raise bad_request("Field '%s' contains an out-of-range value." % name)
        out.append(item)
    return out


def want_action(body, allowed):
    return want_enum(body, "action", allowed, required=True)


def forbid(body, name, action):
    """A companion field supplied for the wrong action is a malformed body."""
    if name in body and body[name] is not None:
        raise bad_request("Field '%s' is not accepted with action %s." % (name, action))


def want_instant(body, name, required=True, default=None):
    from store import parse_instant

    value = want_string(body, name, required=required, default=None)
    if value is None:
        return default
    parsed = parse_instant(value)
    if parsed is None:
        raise bad_request("Field '%s' must be an ISO 8601 instant." % name)
    return parsed


# ------------------------------------------------------------- pagination 2.3
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise bad_request("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad_request("Query parameter 'offset' may not be negative.")
    return limit, offset


def _value_matches(row_value, wanted):
    if isinstance(row_value, bool):
        low = wanted.strip().lower()
        if low in ("true", "1"):
            return row_value is True
        if low in ("false", "0"):
            return row_value is False
        return False
    if row_value is None:
        return wanted.strip().lower() in ("null", "none", "")
    if isinstance(row_value, int):
        try:
            return row_value == int(wanted.strip())
        except (TypeError, ValueError):
            return False
    if isinstance(row_value, Decimal):
        try:
            return row_value == D(wanted.strip())
        except Exception:
            return False
    return str(row_value) == wanted


def apply_filters(rows, field_names, aliases=None):
    """Conjunctive equality filters (PRD 2.3)."""
    args = request.args
    out = rows
    for name in field_names:
        if name not in args:
            continue
        wanted = args.get(name)
        field = (aliases or {}).get(name, name)
        if field == "__subject_codes__":
            out = [r for r in out if wanted in (r.get("subject_codes") or [])]
        else:
            out = [r for r in out if _value_matches(r.get(field), wanted)]
    return out


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    return rows[offset:offset + limit], limit, offset, total
