"""Request-level concerns: authentication, RBAC, request-shape parsing.

Auth headers and role names come from PRD 2.1:
  X-User-ID    - opaque operator id, or the CreditAccount id for the
                 entity-backed roles (Customer, Contractor)
  X-User-Role  - one of StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin,
                 Customer, Contractor
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from response import LIMIT_DEFAULT, LIMIT_MAX, LIMIT_MIN, OFFSET_DEFAULT

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

STORE_ADMIN = "StoreAdmin"
GUEST_SERVICE = "GuestService"
FRAUD_ANALYST = "FraudAnalyst"
FINANCE_ADMIN = "FinanceAdmin"
CUSTOMER = "Customer"
CONTRACTOR = "Contractor"

KNOWN_ROLES = {
    STORE_ADMIN,
    GUEST_SERVICE,
    FRAUD_ANALYST,
    FINANCE_ADMIN,
    CUSTOMER,
    CONTRACTOR,
}

STAFF_ROLES = {STORE_ADMIN, GUEST_SERVICE, FRAUD_ANALYST, FINANCE_ADMIN}
ENTITY_ROLES = {CUSTOMER, CONTRACTOR}


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


# ---------------------------------------------------------------------------
# Ladder step 1 + 2: authentication then role authorization
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    role = request.headers.get(USER_ROLE_HEADER)
    user_id = request.headers.get(USER_ID_HEADER)

    if role is None or not str(role).strip() or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN")
    return Caller(user_id if user_id is not None else "", role)


def require_account_ownership(caller, account_id):
    """Entity-backed roles (Customer / Contractor) act only on their own
    account (PRD 2.1): X-User-ID must equal the addressed account id."""
    if caller.role in ENTITY_ROLES and caller.user_id != account_id:
        raise ApiError("ERR_FORBIDDEN",
                       "Entity-backed role may only act on its own account")


# ---------------------------------------------------------------------------
# Ladder step 4: request shape (ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def bad_request(detail=None):
    return ApiError("ERR_INVALID_REQUEST", detail)


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        if request.data and request.data.strip():
            raise bad_request("Request body is not valid JSON")
        return {}
    if not isinstance(body, dict):
        raise bad_request("Request body must be a JSON object")
    return body


def _present(body, name):
    return name in body and body[name] is not None


def require_present(body, name):
    if not _present(body, name):
        raise bad_request("Missing required field '%s'" % name)
    return body[name]


def req_string(body, name, min_length=1):
    value = require_present(body, name)
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string" % name)
    if len(value) < min_length:
        raise bad_request("Field '%s' must be at least %d character(s)"
                          % (name, min_length))
    return value


def opt_string(body, name, default=None, min_length=0):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string" % name)
    if len(value) < min_length:
        raise bad_request("Field '%s' must be at least %d character(s)"
                          % (name, min_length))
    return value


def _check_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer" % name)
    return value


def req_int(body, name, minimum=None, maximum=None):
    value = _check_int(require_present(body, name), name)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be <= %s" % (name, maximum))
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum)


def _to_decimal(value, name):
    if isinstance(value, bool):
        raise bad_request("Field '%s' must be a number" % name)
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            raise bad_request("Field '%s' must be a number" % name)
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            raise bad_request("Field '%s' must be a number" % name)
    raise bad_request("Field '%s' must be a number" % name)


def req_number(body, name, minimum=None, maximum=None,
               minimum_exclusive=False, maximum_exclusive=False):
    value = _to_decimal(require_present(body, name), name)
    if not value.is_finite():
        raise bad_request("Field '%s' must be a finite number" % name)
    if minimum is not None:
        bound = Decimal(str(minimum))
        if minimum_exclusive:
            if value <= bound:
                raise bad_request("Field '%s' must be > %s" % (name, minimum))
        elif value < bound:
            raise bad_request("Field '%s' must be >= %s" % (name, minimum))
    if maximum is not None:
        bound = Decimal(str(maximum))
        if maximum_exclusive:
            if value >= bound:
                raise bad_request("Field '%s' must be < %s" % (name, maximum))
        elif value > bound:
            raise bad_request("Field '%s' must be <= %s" % (name, maximum))
    return value


def opt_number(body, name, default=None, minimum=None, maximum=None,
               minimum_exclusive=False, maximum_exclusive=False):
    if not _present(body, name):
        return default
    return req_number(body, name, minimum=minimum, maximum=maximum,
                      minimum_exclusive=minimum_exclusive,
                      maximum_exclusive=maximum_exclusive)


def req_date_string(body, name):
    value = require_present(body, name)
    return parse_date_string(value, name)


def parse_date_string(value, name):
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be an ISO date (YYYY-MM-DD)" % name)
    text = value.strip()
    if len(text) != 10:
        raise bad_request("Field '%s' must be an ISO date (YYYY-MM-DD)" % name)
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise bad_request("Field '%s' must be an ISO date (YYYY-MM-DD)" % name)


def req_enum(body, name, allowed):
    value = require_present(body, name)
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("Field '%s' must be one of %s" % (name, sorted(allowed)))
    return value


def req_id(body, name):
    value = require_present(body, name)
    if not isinstance(value, str) or not value.strip():
        raise bad_request("Field '%s' must be a non-empty string identifier" % name)
    return value


def opt_id(body, name, default=None):
    if not _present(body, name):
        return default
    return req_id(body, name)


def parse_timestamp(body, name):
    value = require_present(body, name)
    return parse_timestamp_value(value, name)


def parse_timestamp_value(value, name):
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be an ISO 8601 timestamp" % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise bad_request("Field '%s' must be an ISO 8601 timestamp" % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise bad_request("Query parameter 'limit' must be between %d and %d"
                              % (LIMIT_MIN, LIMIT_MAX))
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be >= 0")
    return limit, offset


def query_param(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None
