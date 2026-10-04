"""Auth header extraction, role checking and shared request helpers."""

from flask import request

from errors import ApiError, ERR_MISSING_USER_CONTEXT_HEADER, ERR_INSUFFICIENT_PERMISSIONS

# The six role names, spelled exactly as the programme declares them.
RATING_ADMIN = "RatingAdmin"
HOSPITAL_RESPONDENT = "HospitalRespondent"
VERIFICATION_ANALYST = "VerificationAnalyst"
RATING_ENGINE = "RatingEngine"
PURCHASER_ADMIN = "PurchaserAdmin"
ANY_AUTHENTICATED = "AnyAuthenticated"

ALL_OPERATIONAL_ROLES = [
    RATING_ADMIN,
    HOSPITAL_RESPONDENT,
    VERIFICATION_ANALYST,
    RATING_ENGINE,
    PURCHASER_ADMIN,
]

# A read permits any principal holding a valid header pair.
READ_ROLES = ALL_OPERATIONAL_ROLES + [ANY_AUTHENTICATED]


def user_context():
    """Read X-User-ID / X-User-Role. Missing or empty is refused first."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError(ERR_MISSING_USER_CONTEXT_HEADER)
    if role is None or str(role).strip() == "":
        raise ApiError(ERR_MISSING_USER_CONTEXT_HEADER)
    return str(user_id).strip(), str(role).strip()


def authorize(allowed_roles):
    """Establish identity, then confirm the role holds the operation."""
    user_id, role = user_context()
    if role not in allowed_roles:
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS)
    return user_id, role


def require_read():
    return authorize(READ_ROLES)


# ---------------------------------------------------------------------------
# Body / query helpers
# ---------------------------------------------------------------------------

def body_json():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def query_params():
    return request.args


def has_key(payload, key):
    return key in payload and payload.get(key) is not None


def require_string(payload, key, error_id=None):
    from errors import ERR_INVALID_REQUEST
    value = payload.get(key)
    if value is None or not isinstance(value, str) or value.strip() == "":
        raise ApiError(error_id or ERR_INVALID_REQUEST)
    return value


def require_int(payload, key, minimum=None, error_id=None):
    from errors import ERR_INVALID_REQUEST
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(error_id or ERR_INVALID_REQUEST)
    if minimum is not None and value < minimum:
        raise ApiError(error_id or ERR_INVALID_REQUEST)
    return value


def optional_int(payload, key, default, minimum=None, error_id=None):
    if key not in payload or payload.get(key) is None:
        return default
    return require_int(payload, key, minimum=minimum, error_id=error_id)


def require_number(payload, key, minimum=None, error_id=None):
    from errors import ERR_INVALID_REQUEST
    from db import to_decimal
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ApiError(error_id or ERR_INVALID_REQUEST)
    try:
        dec = to_decimal(value)
    except Exception:
        raise ApiError(error_id or ERR_INVALID_REQUEST)
    if minimum is not None and dec < to_decimal(minimum):
        raise ApiError(error_id or ERR_INVALID_REQUEST)
    return dec


def optional_number(payload, key, default=None, error_id=None):
    if key not in payload or payload.get(key) is None:
        return default
    return require_number(payload, key, error_id=error_id)


def require_instant(payload, key, error_id=None):
    from errors import ERR_INVALID_REQUEST
    from db import parse_instant
    value = payload.get(key)
    if value is None or not isinstance(value, str):
        raise ApiError(error_id or ERR_INVALID_REQUEST)
    try:
        return parse_instant(value)
    except ValueError:
        raise ApiError(error_id or ERR_INVALID_REQUEST)


def require_array(payload, key, error_id=None):
    from errors import ERR_INVALID_REQUEST
    value = payload.get(key)
    if not isinstance(value, list):
        raise ApiError(error_id or ERR_INVALID_REQUEST)
    return value


def paginate(items, error_id=None):
    """Apply the declared limit/offset defaults and render the envelope.

    limit defaults to 10 and must fall between 1 and 100 inclusive;
    offset defaults to 0.
    """
    from errors import ERR_INVALID_REQUEST
    params = query_params()
    limit_raw = params.get("limit")
    offset_raw = params.get("offset")

    limit = 10
    if limit_raw is not None and str(limit_raw) != "":
        try:
            limit = int(str(limit_raw))
        except ValueError:
            raise ApiError(error_id or ERR_INVALID_REQUEST)
        if limit < 1 or limit > 100:
            raise ApiError(error_id or ERR_INVALID_REQUEST)

    offset = 0
    if offset_raw is not None and str(offset_raw) != "":
        try:
            offset = int(str(offset_raw))
        except ValueError:
            raise ApiError(error_id or ERR_INVALID_REQUEST)
        if offset < 0:
            raise ApiError(error_id or ERR_INVALID_REQUEST)

    total = len(items)
    window = items[offset:offset + limit]
    return window, limit, offset, total


def single_filter_param(name):
    value = query_params().get(name)
    if value is None or str(value) == "":
        return None
    return str(value)