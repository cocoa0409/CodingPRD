"""Authentication, authorisation, request-body shape and pagination checks.

Rungs 1, 2, 3 and 8 of the validation ladder in PRD section 2.6.
"""

from flask import request

from common import ApiError, D, invalid, is_date, parse_dt

ROLES = (
    "VineyardManager",
    "Agronomist",
    "Applicator",
    "ComplianceOfficer",
    "Controller",
    "CrewSupervisor",
    "ClientOwner",
)

ALL_ROLES = list(ROLES)


# --------------------------------------------------------------------------
# Rung 1 / rung 2
# --------------------------------------------------------------------------


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    if not str(user_id).strip() or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    return str(user_id), role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", 403)


def auth(allowed):
    """Rung 1 then rung 2, in that order."""
    user_id, role = authenticate()
    authorize(role, allowed)
    return user_id, role


# --------------------------------------------------------------------------
# Rung 3 — body shape
# --------------------------------------------------------------------------


class F(object):
    """One field of a request-body schema."""

    def __init__(self, name, kind, required=True, values=None, gt=None,
                 ge=None, le=None, lt=None, min_len=None, max_len=None,
                 nullable=False, blank_ok=False):
        self.name = name
        self.kind = kind
        self.required = required
        self.values = values
        self.gt = gt
        self.ge = ge
        self.le = le
        self.lt = lt
        self.min_len = min_len
        self.max_len = max_len
        self.nullable = nullable
        self.blank_ok = blank_ok


def raw_body():
    data = request.get_data()
    if data is None or len(data.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        raise invalid("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        raise invalid("Request body must be a JSON object.")
    return parsed


def _check_number(field, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("Field '%s' must be a number." % field.name)
    dec = D(value)
    if field.gt is not None and not dec > D(field.gt):
        raise invalid("Field '%s' must be greater than %s." % (field.name, field.gt))
    if field.ge is not None and not dec >= D(field.ge):
        raise invalid("Field '%s' must be at least %s." % (field.name, field.ge))
    if field.lt is not None and not dec < D(field.lt):
        raise invalid("Field '%s' must be less than %s." % (field.name, field.lt))
    if field.le is not None and not dec <= D(field.le):
        raise invalid("Field '%s' must be at most %s." % (field.name, field.le))
    return dec


def _check_integer(field, value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("Field '%s' must be an integer." % field.name)
    if field.gt is not None and not value > field.gt:
        raise invalid("Field '%s' must be greater than %s." % (field.name, field.gt))
    if field.ge is not None and not value >= field.ge:
        raise invalid("Field '%s' must be at least %s." % (field.name, field.ge))
    if field.lt is not None and not value < field.lt:
        raise invalid("Field '%s' must be less than %s." % (field.name, field.lt))
    if field.le is not None and not value <= field.le:
        raise invalid("Field '%s' must be at most %s." % (field.name, field.le))
    return value


def _check_string(field, value):
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % field.name)
    if not field.blank_ok and field.min_len and not value.strip():
        raise invalid("Field '%s' must not be blank." % field.name)
    if field.min_len is not None and len(value) < field.min_len:
        raise invalid("Field '%s' is too short." % field.name)
    if field.max_len is not None and len(value) > field.max_len:
        raise invalid("Field '%s' is too long." % field.name)
    return value


def parse_payload(schema):
    """Validate the body against `schema` and return a normalised dict.

    Absent optional fields are simply missing from the returned dict; an
    explicit JSON null on a nullable optional field is treated as absent.
    """
    body = raw_body()
    known = set(f.name for f in schema)
    for key in body:
        if key not in known:
            raise invalid("Unknown field '%s'." % key)

    out = {}
    for field in schema:
        present = field.name in body
        value = body.get(field.name)
        if present and value is None and (field.nullable or not field.required):
            present = False
        if not present:
            if field.required:
                raise invalid("Field '%s' is required." % field.name)
            continue

        kind = field.kind
        if kind == "string":
            out[field.name] = _check_string(field, value)
        elif kind == "id":
            out[field.name] = _check_string(field, value)
        elif kind == "number":
            out[field.name] = _check_number(field, value)
        elif kind == "integer":
            out[field.name] = _check_integer(field, value)
        elif kind == "boolean":
            if not isinstance(value, bool):
                raise invalid("Field '%s' must be a boolean." % field.name)
            out[field.name] = value
        elif kind == "enum":
            if not isinstance(value, str) or value not in field.values:
                raise invalid("Field '%s' is not one of %s." % (field.name, field.values))
            out[field.name] = value
        elif kind == "enum_array":
            if not isinstance(value, list) or len(value) == 0:
                raise invalid("Field '%s' must be a non-empty array." % field.name)
            seen = set()
            for item in value:
                if not isinstance(item, str) or item not in field.values:
                    raise invalid("Field '%s' contains an unknown value." % field.name)
                if item in seen:
                    raise invalid("Field '%s' contains duplicates." % field.name)
                seen.add(item)
            out[field.name] = list(value)
        elif kind == "datetime":
            parsed = parse_dt(value) if isinstance(value, str) else None
            if parsed is None:
                raise invalid("Field '%s' must be an ISO 8601 instant." % field.name)
            out[field.name] = value
            out["_dt_" + field.name] = parsed
        elif kind == "date":
            if not is_date(value):
                raise invalid("Field '%s' must be a YYYY-MM-DD date." % field.name)
            out[field.name] = value
        elif kind == "email":
            _check_string(field, value)
            if value.count("@") != 1:
                raise invalid("Field '%s' must contain exactly one '@'." % field.name)
            out[field.name] = value
        else:  # pragma: no cover - defensive
            raise invalid("Unsupported field kind for '%s'." % field.name)
    return out


# --------------------------------------------------------------------------
# Rung 8 — pagination (PRD 2.3)
# --------------------------------------------------------------------------


def _as_int(raw):
    text = raw.strip()
    if text.startswith("+"):
        text = text[1:]
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        return None
    value = int(digits)
    return -value if negative else value


def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        parsed = _as_int(raw_limit)
        if parsed is None or parsed < 1 or parsed > 100:
            raise invalid("limit must be an integer between 1 and 100.")
        limit = parsed
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        parsed = _as_int(raw_offset)
        if parsed is None or parsed < 0:
            raise invalid("offset must be an integer of at least 0.")
        offset = parsed
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
