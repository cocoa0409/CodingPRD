"""Response envelope, pagination and the authentication / authorization tiers."""

from flask import jsonify, request

from errors import ApiError
from store import clock_iso
from util import new_request_id

ROLES = (
    "PlatformAdmin",
    "SelectionManager",
    "Applicant",
    "PlacementCoordinator",
    "InstituteDirector",
    "CertificationOfficer",
    "Coach",
)

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _meta():
    return {"api_request_id": new_request_id(), "api_request_timestamp": clock_iso()}


def ok(data, status=200, page=None, response_type=None):
    meta = _meta()
    if page:
        meta.update(page)
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def error_body(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )


def read_json():
    """Every operation with a body reads it through here; a non-object body is a
    malformed request (tier 3) rather than a crash."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return body


def _parse_page_int(raw, name, default):
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "The %s query parameter is malformed." % name)
    return value


def paginate(items):
    """Slice an already ordered collection and build the envelope's page window."""
    limit = _parse_page_int(request.args.get("limit"), "limit", PAGE_LIMIT_DEFAULT)
    offset = _parse_page_int(request.args.get("offset"), "offset", PAGE_OFFSET_DEFAULT)
    if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "The limit query parameter must be between %d and %d." % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX),
        )
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "The offset query parameter must not be negative.")
    total = len(items)
    page = items[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }


def require_auth(roles, skip_header_check=False):
    """Tier 1 (authentication) then tier 2 (authorization).

    `skip_header_check` is set only for the clock-setting capability, the sole
    operation exempt from the header check; the role check still applies.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not skip_header_check:
        if not user_id or not role or role not in ROLES:
            raise ApiError("ERR_UNAUTHENTICATED")
    if role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return user_id, role


def sorted_by_created(table):
    return sorted(table, key=lambda row: (row.get("created_at") or "",))
