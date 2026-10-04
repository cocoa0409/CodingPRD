"""Request plumbing: auth middleware, body binding, pagination, references.

Auth follows PRD §2.1 verbatim:

* both `X-User-ID` and `X-User-Role` are required; a missing header, an empty
  value, or a role string that does not name one of the declared roles is refused
  with `ERR_UNAUTHENTICATED` and HTTP 401;
* a well-formed but unpermitted role is refused with `ERR_UNAUTHORIZED` and 403;
* "These two checks are the highest-priority rules in the system: authentication
  is decided before authorisation, and authorisation is decided before any
  resource is looked up."
"""

import functools

from flask import request

import db
import models
from core import ApiError, PRIORITY_AUTH, PRIORITY_UNAUTHORIZED

# PRD §2.1 — "The recognised role names, spelled exactly as they must appear in
# the X-User-Role header".
ROLES = {
    "Any", "PlatformAdmin", "CorridorOperationsManager", "ComplianceOfficer",
    "CarrierDispatcher", "TerminalManager", "RemoteSupportSupervisor",
    "RemoteSupportOperator", "IncidentReviewer", "SafetyCaseAuthor",
    "RegulatoryLiaison", "FleetMaintenanceTech", "DriverOutreachCoordinator",
    "ShipperPartnershipManager", "BookingClerk", "TerminalOperator",
    "ExchangeParticipant",
}

# The only entity-backed role — PRD §2.1 / §3.4.
ENTITY_BACKED_ROLE = "RemoteSupportOperator"


def _identity():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or str(uid).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID and X-User-Role headers are required.")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID and X-User-Role headers are required.")
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-Role does not name a declared role.")
    return str(uid).strip(), role


def require_auth(roles):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = _identity()
            if "Any" in roles:
                permitted = True
            else:
                permitted = role in roles
            if not permitted:
                raise ApiError("ERR_UNAUTHORIZED",
                               "The caller's role is not permitted for this operation.")
            request.ctx_uid = uid
            request.ctx_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def actor_id():
    return getattr(request, "ctx_uid", None)


def actor_role():
    return getattr(request, "ctx_role", None)


def body():
    """The JSON object body, or an empty dict when none was supplied."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def bind(entity, public=None):
    """Validate a body against an entity's declared input schema.

    §2.11: "a required body field is missing, a field arrives with the wrong
    type, or a field is supplied that the endpoint does not declare" is
    `ERR_INVALID_REQUEST` (422).
    """
    raw = body()
    allowed = set(models.INPUT_FIELDS[entity]) if public is None else set(public)
    for key in raw:
        if key not in allowed:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % key)
    payload = models.defaults_payload(entity, raw)
    missing = models.missing_public(entity, raw, public)
    if missing is not None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Required field '%s' is missing." % missing)
    return payload


def pagination():
    """§2.3: `limit` defaults to 10 with a minimum of 1 and a maximum of 100;
    `offset` defaults to 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw not in (None, "") else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset_raw) if offset_raw not in (None, "") else 0
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


# Path-existence errors, priority 3-8 (§2.11).
PATH_ERRORS = {
    "Corridor": "ERR_CORRIDOR_NOT_FOUND",
    "RunPlan": "ERR_RUN_PLAN_NOT_FOUND",
    "Terminal": "ERR_TERMINAL_NOT_FOUND",
    "Carrier": "ERR_CARRIER_NOT_FOUND",
    "ShipperCommitment": "ERR_COMMITMENT_NOT_FOUND",
    "IncidentReport": "ERR_INCIDENT_NOT_FOUND",
}

# Body/query references named in §2.11 priority 9.
REFERENCE_ERROR = "ERR_REFERENCE_NOT_FOUND"


def must_get(entity, rid):
    """Resolve a path identifier, raising the entity's own not-found error."""
    row = db.get(models.TABLE[entity], rid)
    if row is None:
        raise ApiError(PATH_ERRORS.get(entity, "ERR_REFERENCE_NOT_FOUND"))
    return row


def must_resolve(entity, rid):
    """Resolve an identifier supplied outside the path — `ERR_REFERENCE_NOT_FOUND`."""
    if rid is None:
        raise ApiError(REFERENCE_ERROR)
    row = db.get(models.TABLE[entity], rid)
    if row is None:
        raise ApiError(REFERENCE_ERROR)
    return row


def get_or_none(entity, rid):
    if rid is None:
        return None
    return db.get(models.TABLE[entity], rid)


def check_occ(raw_body, field, row, public):
    """§2.9: the check is a pure equality test against the current version; when
    the field is omitted, skip the check.  Supplying it where the endpoint does
    not declare it is an unknown field (ERR_INVALID_REQUEST)."""
    if field not in public:
        if field in raw_body:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % field)
        return
    if field not in raw_body:
        return
    supplied = raw_body[field]
    if supplied is None:
        return
    if int(supplied) != int(row.get("version", 1)):
        raise ApiError("ERR_STALE_VERSION",
                       "The supplied expected version does not match the current version.")


def require_enum(value, allowed, error_id="ERR_INVALID_REQUEST"):
    if value not in allowed:
        raise ApiError(error_id)
    return value


def coerce_int(value, error_id="ERR_INVALID_REQUEST"):
    if isinstance(value, bool) or value is None:
        raise ApiError(error_id)
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        raise ApiError(error_id)


def coerce_num(value, error_id="ERR_INVALID_REQUEST"):
    if isinstance(value, bool) or value is None:
        raise ApiError(error_id)
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value))
    except (TypeError, ValueError):
        raise ApiError(error_id)