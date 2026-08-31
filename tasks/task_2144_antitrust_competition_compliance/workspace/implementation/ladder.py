"""Validation-ladder primitives (PRD 2.7) and request-scoped bookkeeping."""
from decimal import Decimal, InvalidOperation

from flask import g, request

from errors import fail
from store import db, parse_iso, now_wall

ROLES = ["ComplianceAdmin", "AntitrustCounsel", "BusinessLead", "Employee"]
ALL_ROLES = list(ROLES)


# ----------------------------------------------------------- dirty bookkeeping
def dirty_set():
    if not hasattr(g, "_dirty"):
        g._dirty = []
    return g._dirty


def touch(row):
    """Mark a row mutated; version bumps exactly once per row per request."""
    if row is None:
        return
    bucket = dirty_set()
    for existing in bucket:
        if existing is row:
            return
    bucket.append(row)


def commit():
    """Apply the per-request version/updated_at bumps."""
    ts = now_wall()
    for row in dirty_set():
        row["version"] = int(row.get("version", 1)) + 1
        row["updated_at"] = ts
    g._dirty = []


# -------------------------------------------------------- rung 1 + rung 2: auth
def require_auth(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "authentication headers missing or invalid")
    if allowed_roles is not None and role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "role %s may not perform this operation" % role)
    return role, user_id


# ----------------------------------------------------------- rung 3: body shape
def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return payload


def _present(payload, name):
    return name in payload and payload[name] is not None


def req_str(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    value = payload[name]
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string" % name)
    return value


def req_enum(payload, name, members, required=True, default=None):
    if not _present(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in members:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(members)))
    return value


def req_int(payload, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, maximum))
    return value


def req_num(payload, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number" % name)
    try:
        dec = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    except (InvalidOperation, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be a number" % name)
    if minimum is not None and dec < Decimal(str(minimum)):
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, maximum))
    return dec


def req_bool(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    value = payload[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return value


def req_dt(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default
    parsed = parse_iso(payload[name])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC datetime" % name)
    return parsed


def req_enum_array(payload, name, members, required=True, allow_empty=True, default=None):
    if not _present(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default if default is not None else []
    value = payload[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array" % name)
    if not allow_empty and len(value) == 0:
        fail("ERR_INVALID_REQUEST", "%s must be non-empty" % name)
    for item in value:
        if not isinstance(item, str) or item not in members:
            fail("ERR_INVALID_REQUEST", "%s contains an undeclared member" % name)
    return list(value)


def req_str_array(payload, name, required=True, allow_empty=True, default=None):
    if not _present(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return default if default is not None else []
    value = payload[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array" % name)
    if not allow_empty and len(value) == 0:
        fail("ERR_INVALID_REQUEST", "%s must be non-empty" % name)
    for item in value:
        if not isinstance(item, str):
            fail("ERR_INVALID_REQUEST", "%s must contain strings" % name)
    return list(value)


def req_affected_years(payload, name="affected_years"):
    if not _present(payload, name):
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    value = payload[name]
    if not isinstance(value, list) or len(value) == 0:
        fail("ERR_INVALID_REQUEST", "affected_years must be a non-empty array")
    out = []
    for item in value:
        if not isinstance(item, dict):
            fail("ERR_INVALID_REQUEST", "affected_years entries must be objects")
        year = item.get("year")
        cents = item.get("affected_commerce_cents")
        if isinstance(year, bool) or not isinstance(year, int):
            fail("ERR_INVALID_REQUEST", "affected_years[].year must be an integer")
        if isinstance(cents, bool) or not isinstance(cents, int):
            fail("ERR_INVALID_REQUEST", "affected_years[].affected_commerce_cents must be an integer")
        if cents < 0:
            fail("ERR_INVALID_REQUEST", "affected_years[].affected_commerce_cents must be >= 0")
        out.append({"year": year, "affected_commerce_cents": cents})
    return out


# ------------------------------------------------------ rung 4: pagination shape
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer")
        if str(raw).strip() != str(limit):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer")
        if str(raw).strip() != str(offset):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be >= 0")
    return limit, offset


def filter_enum(name, members):
    """A list filter whose value must be a declared enum member (PRD 2.3)."""
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in members:
        fail("ERR_INVALID_REQUEST", "%s is not a declared member" % name)
    return value


def filter_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


# ------------------------------------------------- rungs 5/6: existence lookups
_NOT_FOUND = {
    "business_units": "ERR_BUSINESS_UNIT_NOT_FOUND",
    "employees": "ERR_EMPLOYEE_NOT_FOUND",
    "curricula": "ERR_CURRICULUM_NOT_FOUND",
    "assignments": "ERR_TRAINING_ASSIGNMENT_NOT_FOUND",
    "associations": "ERR_ASSOCIATION_NOT_FOUND",
    "participations": "ERR_PARTICIPATION_NOT_FOUND",
    "meetings": "ERR_MEETING_NOT_FOUND",
    "attendances": "ERR_ATTENDANCE_NOT_FOUND",
    "contacts": "ERR_CONTACT_NOT_FOUND",
    "transactions": "ERR_TRANSACTION_NOT_FOUND",
    "hsr_analyses": "ERR_HSR_ANALYSIS_NOT_FOUND",
    "sites": "ERR_SITE_NOT_FOUND",
    "drills": "ERR_DRILL_NOT_FOUND",
    "document_audits": "ERR_DOCUMENT_AUDIT_NOT_FOUND",
    "leniency_applications": "ERR_LENIENCY_APPLICATION_NOT_FOUND",
    "risk_assessments": "ERR_RISK_ASSESSMENT_NOT_FOUND",
}


def lookup(collection, row_id):
    table = getattr(db, collection)
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(_NOT_FOUND[collection], "%s does not resolve" % collection)
    return row


def rows(collection):
    return list(getattr(db, collection).values())
