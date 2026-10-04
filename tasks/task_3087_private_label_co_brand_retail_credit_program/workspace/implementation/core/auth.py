"""Request plumbing: auth headers, role matrix, body/query helpers (PRD §2.1).

Every request must carry `X-User-ID` and `X-User-Role`; a missing or malformed
header pair is `ERR_UNAUTHENTICATED` (401). A valid but unpermitted role is
`ERR_UNAUTHORIZED` (403), evaluated before any resource is loaded (PRD §2.11).
"""
from flask import request

from . import errors
from .errors import (
    ERR_INVALID_REQUEST,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    fail,
)

ROLES = (
    "ProgramAdmin",
    "RetailPartnerAnalyst",
    "Underwriter",
    "CardholderService",
    "Cardholder",
    "Applicant",
    "CoBrandIssuer",
)


def get_headers():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise fail(ERR_UNAUTHENTICATED,
                   "X-User-ID and X-User-Role headers must both be present "
                   "and carry a recognized role.")
    return user_id, role


def require_role(*allowed):
    """Reject a role outside the operation's authorized set (403) (PRD §2.1)."""
    user_id, role = get_headers()
    if role not in allowed:
        raise fail(ERR_UNAUTHORIZED,
                   f"Role '{role}' is not permitted for this operation.")
    return user_id, role


def require_any_authenticated():
    return get_headers()


# ---------------------------------------------------------------------------
# Request envelope values
# ---------------------------------------------------------------------------

_PAGINATION_MIN = 1
_PAGINATION_MAX = 100
_PAGINATION_DEFAULT = 10


def body() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise fail(ERR_INVALID_REQUEST, "The request body must be a JSON object.")
    return data


def pagination():
    """(limit, offset) with the declared defaults and bounds (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = _PAGINATION_DEFAULT
    offset = 0
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise fail(ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < _PAGINATION_MIN or limit > _PAGINATION_MAX:
            raise fail(ERR_INVALID_REQUEST,
                       f"limit must be between {_PAGINATION_MIN} and {_PAGINATION_MAX}.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise fail(ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            raise fail(ERR_INVALID_REQUEST, "offset must be non-negative.")
    return limit, offset


def apply_filters(rows, filters):
    """Apply optional FK query filters; a supplied filter must equal the field."""
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return rows


def page(rows, limit, offset):
    return rows[offset:offset + limit]


# ---------------------------------------------------------------------------
# Typed body-field extraction (PRD §3.4: a missing or ill-typed required input
# is refused with ERR_INVALID_REQUEST / 400).
# ---------------------------------------------------------------------------

def _wrong_type(value, kind: str) -> bool:
    if kind == "string":
        return not isinstance(value, str)
    if kind == "int":
        return isinstance(value, bool) or not isinstance(value, int)
    if kind == "number":
        return isinstance(value, bool) or not isinstance(value, (int, float))
    if kind == "bool":
        return not isinstance(value, bool)
    return False


def require_field(payload: dict, name: str, kind: str):
    if name not in payload or payload[name] is None:
        raise fail(ERR_INVALID_REQUEST, f"'{name}' is a required input field.")
    value = payload[name]
    if _wrong_type(value, kind):
        raise fail(ERR_INVALID_REQUEST, f"'{name}' must be a {kind}.")
    if kind == "number":
        return float(value)
    return value


def optional_field(payload: dict, name: str, kind: str, default=None):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if _wrong_type(value, kind):
        raise fail(ERR_INVALID_REQUEST, f"'{name}' must be a {kind}.")
    if kind == "number":
        return float(value)
    return value


def enum_field(payload: dict, name: str, allowed, required=True, default=None):
    if name not in payload or payload[name] is None:
        if required:
            raise fail(ERR_INVALID_REQUEST, f"'{name}' is a required input field.")
        return default
    value = payload[name]
    if value not in allowed:
        raise fail(ERR_INVALID_REQUEST,
                   f"'{name}' must be one of {sorted(allowed)}.")
    return value


# Re-exported for route modules that raise errors directly.
__all__ = [
    "ROLES", "get_headers", "require_role", "require_any_authenticated",
    "body", "pagination", "apply_filters", "page",
    "require_field", "optional_field", "enum_field",
    "errors",
]