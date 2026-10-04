"""Identity extraction and RBAC (PRD §2.1, §2.12; SCAFFOLD §1.7).

Two headers carry identity: ``X-User-Role`` names the acting role and
``X-User-ID`` identifies the acting party.  Either one missing or empty is
``ERR_UNAUTHENTICATED`` (401).  A role that is not permitted for the requested
operation is ``ERR_UNAUTHORIZED`` (403).  Both checks precede every existence,
state and business check (validation priorities 1 and 2).
"""

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLE_HEADER = "X-User-Role"
ID_HEADER = "X-User-ID"

ROLES = (
    "PlatformAdmin",
    "AppointingExecutive",
    "FieldManager",
    "AgencyPrincipal",
    "ClaimsAdjuster",
    "RegulatoryBoard",
    "StaffMember",
)

# Roles whose X-User-ID is an opaque operator identifier (never compared to an
# entity id); the rest are entity backed.
OPAQUE_ROLES = {
    "PlatformAdmin",
    "AppointingExecutive",
    "FieldManager",
    "ClaimsAdjuster",
    "RegulatoryBoard",
}


def identity(request):
    """Return (role, user_id) or raise ERR_UNAUTHENTICATED."""
    role = request.headers.get(ROLE_HEADER)
    user_id = request.headers.get(ID_HEADER)
    if role is None or str(role).strip() == "":
        raise ApiError(ERR_UNAUTHENTICATED)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError(ERR_UNAUTHENTICATED)
    return str(role).strip(), str(user_id).strip()


def authorize(request, allowed_roles):
    """Authenticate, then confirm the role is permitted for the operation."""
    role, user_id = identity(request)
    if allowed_roles and role not in allowed_roles:
        raise ApiError(ERR_UNAUTHORIZED)
    return role, user_id


def is_opaque(role):
    return role in OPAQUE_ROLES


def require_agency_ownership(role, user_id, agency_id):
    """An AgencyPrincipal is identified by the id of the acting Agency, and
    ownership checks on any agency-scoped resource compare that resource's
    agency foreign key to X-User-ID (PRD §2.1)."""
    if role == "AgencyPrincipal" and str(user_id) != str(agency_id):
        raise ApiError(ERR_UNAUTHORIZED)


def require_self(role, user_id, record_id):
    """A StaffMember is identified by its own record id and is read-only on
    itself and its sponsoring agreement (PRD §3.5)."""
    if role == "StaffMember" and str(user_id) != str(record_id):
        raise ApiError(ERR_UNAUTHORIZED)


def paginate(request, total):
    """Read limit/offset, validate the bounds, and compute the page window.

    Defaults come from response_envelope.pagination_defaults: limit 10 (1..100),
    offset 0.  Values outside the bounds are rejected rather than clamped.
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer.", 400)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION",
                           "limit must be between 1 and 100.", 400)

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer.", 400)
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION",
                           "offset must be zero or greater.", 400)

    window = slice(offset, offset + limit)
    has_more = (offset + limit) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return window, meta


def filter_by(rows, filters):
    """Keep rows whose value for each named filter matches the request value."""
    for field, wanted in filters.items():
        if wanted is None:
            continue
        rows = [r for r in rows if str(r.get(field)) == str(wanted)]
    return rows