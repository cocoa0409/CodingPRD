"""Auth context extraction and pagination helpers.

Header semantics come from PRD section 2.1 and SCAFFOLD section 1.4 priority 1:
X-User-ID and X-User-Role are both mandatory and X-User-Role must name one of the
ten declared roles.
"""

from errors import (
    ApiError,
    ERR_MISSING_USER_CONTEXT,
    ERR_CLIENT_SCOPE_VIOLATION,
    ERR_INSUFFICIENT_PERMISSIONS,
)

# The ten recognised role names, spelled exactly as PRD section 2.1 requires.
ROLES = (
    "ReferenceLabOperations",
    "LabClientAdmin",
    "CourierCoordinator",
    "AccessioningTechnologist",
    "MedicalTechnologist",
    "InterfaceAnalyst",
    "Pathologist",
    "MedicalDirector",
    "LabBillingSpecialist",
    "UtilizationReviewer",
)

# PRD section 2.3 / SCAFFOLD section 1.0 pagination defaults.
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


class Actor:
    """The acting party behind a request."""

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Actor(%r, %r)" % (self.user_id, self.role)


def extract_actor(headers):
    """Validation priority 1: header presence and a declared role value."""
    user_id = headers.get("X-User-ID")
    role = headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError(
            ERR_MISSING_USER_CONTEXT,
            "X-User-ID and X-User-Role headers are both required.",
        )
    if role not in ROLES:
        raise ApiError(
            ERR_MISSING_USER_CONTEXT,
            "X-User-Role %r is not a declared role." % (role,),
        )
    return Actor(user_id, role)


def require_role(actor, allowed):
    """Validation priority 2: the acting role must be permitted."""
    if actor is None:
        raise ApiError(
            ERR_MISSING_USER_CONTEXT,
            "X-User-ID and X-User-Role headers are both required.",
        )
    if actor.role not in allowed:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Role %s may not perform this operation." % (actor.role,),
        )
    return actor


def enforce_client_scope(actor, client_laboratory_id):
    """Validation priority 2.5: a LabClientAdmin may only act on its own client.

    Per PRD section 2.1, X-User-ID for a LabClientAdmin is the id of the acting
    ClientLaboratory, so a mismatch on the resource's client_laboratory_id is a
    scope violation rather than a permission failure.
    """
    if actor is not None and actor.role == "LabClientAdmin":
        if client_laboratory_id is None or client_laboratory_id != actor.user_id:
            raise ApiError(
                ERR_CLIENT_SCOPE_VIOLATION,
                "LabClientAdmin may only act on its own client laboratory.",
            )


def pagination_args(query):
    """Read limit/offset with their declared defaults and bounds.

    A non-integer or out-of-enum value is a request-shape failure. An out-of-range
    integer is clamped into the permitted window rather than rejected.
    """
    from errors import ERR_INVALID_REQUEST

    limit = _int_param(query, "limit", PAGE_DEFAULT_LIMIT, ERR_INVALID_REQUEST)
    offset = _int_param(query, "offset", PAGE_DEFAULT_OFFSET, ERR_INVALID_REQUEST)
    if limit < PAGE_MIN_LIMIT:
        limit = PAGE_MIN_LIMIT
    if limit > PAGE_MAX_LIMIT:
        limit = PAGE_MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def _int_param(query, name, default, error_id):
    raw = query.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError(error_id, "Query parameter %s must be an integer." % (name,))


def paginate(rows, limit, offset):
    """Slice a fully sorted row list and report the page metadata."""
    total = len(rows)
    window = rows[offset: offset + limit]
    has_more = (offset + len(window)) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return window, meta


def sort_by_created(rows):
    """PRD section 2.3: list results are ordered by created_at ascending."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))