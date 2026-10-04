"""Request handling: auth headers, role enforcement, body contracts, paging."""

from flask import request

import db
from errors import (
    ApiError,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_UNAUTHENTICATED,
    ERR_PARTICIPANT_NOT_FOUND,
    ERR_PATIENT_NOT_FOUND,
    ERR_PRESCRIPTION_NOT_FOUND,
    ERR_ENDPOINT_NOT_FOUND,
    ERR_SIGNING_SESSION_NOT_FOUND,
    ERR_BENEFIT_CHECK_NOT_FOUND,
    ERR_ATTEMPT_NOT_FOUND,
    ERR_CONSENT_NOT_FOUND,
    ERR_FEE_ENTRY_NOT_FOUND,
)

ROLES = [
    "NetworkOperator",
    "ParticipantAdmin",
    "Prescriber",
    "Pharmacy",
    "HubOperator",
    "PatientService",
]

# Roles whose X-User-ID must resolve to a participant (§2.1).
ENTITY_BACKED = {
    "ParticipantAdmin": "NetworkParticipant",
    "Prescriber": "NetworkParticipant",
    "Pharmacy": "NetworkParticipant",
}

OPEN_PATHS = {"/network/"}


def _is_open(path):
    """The network metadata read and the test-driving endpoints are exempt from
    the missing-role refusal (§2.9)."""
    return path in OPEN_PATHS or path.startswith("/_")


def actor():
    """Resolve and authorize the caller. Returns (role, user_id).

    Priority 1 -> ERR_UNAUTHENTICATED (401) when X-User-Role is absent or not
    one of the six declared roles. Priority 2 -> ERR_FORBIDDEN_ROLE (403) when
    an entity-backed role's X-User-ID does not identify its backing entity.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is not None and role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED)
    if _is_open(request.path):
        return role, user_id
    if not role:
        raise ApiError(ERR_UNAUTHENTICATED)
    if role in ENTITY_BACKED:
        if not user_id or db.get("participants", user_id) is None:
            raise ApiError(ERR_FORBIDDEN_ROLE)
    return role, user_id


def allowed(role, roles):
    if role is None:
        # Open endpoint reached without a role: nothing to enforce.
        return
    if role not in roles:
        raise ApiError(ERR_FORBIDDEN_ROLE)


HISTORY_RECORD_ROUTE_TAIL = "/patients/<pid>/history-records"


def _is_history_record_route():
    """True on `POST /network/patients/{id}/history-records`.

    The generator emitted that endpoint's path with a literal patient id in place of
    the `{id}` placeholder, so the request carries the patient identifier in the path
    segment the route rule declares as `{id}`. The matched rule is what distinguishes
    the two forms.
    """
    rule = getattr(request, "url_rule", None)
    return rule is not None and str(rule.rule).endswith(HISTORY_RECORD_ROUTE_TAIL)


def same_resource(role, user_id, owner_id):
    """Ownership check for entity-backed roles.

    Opaque roles (NetworkOperator, HubOperator, PatientService) derive no
    ownership from X-User-ID, so they are never compared against a resource.
    """
    if role in ENTITY_BACKED and owner_id is not None and str(user_id) != str(owner_id):
        raise ApiError(ERR_FORBIDDEN_ROLE)


# --------------------------------------------------------------------------
# Body contracts — a declared input that is not a recognised field of the
# request, a missing required field, an unknown enum member or a malformed
# body is refused with ERR_INVALID_REQUEST (400) (§2.9).
# --------------------------------------------------------------------------

def body(required=(), optional=()):
    raw = request.get_json(silent=True)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ApiError(ERR_INVALID_REQUEST, "The request body must be a JSON object.")
    known = set(required) | set(optional)
    for key in raw:
        if key not in known:
            raise ApiError(ERR_INVALID_REQUEST, f"'{key}' is not a recognised field of this request.")
    for key in required:
        if key not in raw or raw[key] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"'{key}' is a required field.")
    return {k: v for k, v in raw.items() if k in known}


def enum_value(value, field, choices):
    if value is None:
        raise ApiError(ERR_INVALID_REQUEST, f"'{field}' is required.")
    if value not in choices:
        raise ApiError(ERR_INVALID_REQUEST, f"'{field}' must be one of {', '.join(choices)}.")
    return value


def int_value(value, field, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_INVALID_REQUEST, f"'{field}' must be an integer.")
    if minimum is not None and value < minimum:
        raise ApiError(ERR_INVALID_REQUEST, f"'{field}' must be at least {minimum}.")
    return value


def number_value(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, f"'{field}' must be a number.")
    return value


def string_value(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ApiError(ERR_INVALID_REQUEST, f"'{field}' must be a non-empty string.")
    return value


# --------------------------------------------------------------------------
# Pagination (§2.3): limit defaults to 10, at least 1, at most 100; offset
# defaults to 0.
# --------------------------------------------------------------------------

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def page_args():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = PAGE_LIMIT_DEFAULT if limit is None else int(limit)
        offset = PAGE_OFFSET_DEFAULT if offset is None else int(offset)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "'limit' and 'offset' must be integers.")
    if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        raise ApiError(ERR_INVALID_REQUEST, f"'limit' must be between {PAGE_LIMIT_MIN} and {PAGE_LIMIT_MAX}.")
    if offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "'offset' must be non-negative.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }


def created_order(rows):
    """List endpoints return resources ordered by creation timestamp ascending."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


# --------------------------------------------------------------------------
# Path resolution — left to right, first unresolvable segment ends the request
# (§2.5).
# --------------------------------------------------------------------------

def need_participant(pid, field="participant_id"):
    row = db.get("participants", pid) if pid else None
    if row is None:
        raise ApiError(ERR_PARTICIPANT_NOT_FOUND)
    return row


def need_patient(pid):
    row = db.get("patients", pid) if pid else None
    if row is None:
        raise ApiError(ERR_PATIENT_NOT_FOUND)
    return row


def need_prescription(pid):
    row = db.get("prescriptions", pid) if pid else None
    if row is None:
        raise ApiError(ERR_PRESCRIPTION_NOT_FOUND)
    return row


def need_endpoint(eid):
    row = db.get("endpoints", eid) if eid else None
    if row is None:
        raise ApiError(ERR_ENDPOINT_NOT_FOUND)
    return row


def need_attempt(aid):
    row = db.get("routing_attempts", aid) if aid else None
    if row is None:
        raise ApiError(ERR_ATTEMPT_NOT_FOUND)
    return row


def need_session(sid):
    row = db.get("signing_sessions", sid) if sid else None
    if row is None:
        raise ApiError(ERR_SIGNING_SESSION_NOT_FOUND)
    return row


def need_benefit_check(bid):
    row = db.get("benefit_checks", bid) if bid else None
    if row is None:
        raise ApiError(ERR_BENEFIT_CHECK_NOT_FOUND)
    return row


def need_consent(cid):
    row = db.get("consents", cid) if cid else None
    if row is None:
        raise ApiError(ERR_CONSENT_NOT_FOUND)
    return row


def need_fee_entry(eid):
    row = db.get("fee_entries", eid) if eid else None
    if row is None:
        raise ApiError(ERR_FEE_ENTRY_NOT_FOUND)
    return row