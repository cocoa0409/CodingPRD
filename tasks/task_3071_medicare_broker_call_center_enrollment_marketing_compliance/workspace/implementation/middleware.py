"""Auth, pagination and id-resolution helpers (PRD 2.1, 2.3, 2.9)."""

from flask import g, request

import db
import serializers
from errors import ApiError


def current_user_id():
    return getattr(g, "user_id", None)


def current_role():
    return getattr(g, "user_role", None)

ROLES = {
    "PlatformAdmin",
    "DirectorOfSales",
    "ComplianceOfficer",
    "LicensingCoordinator",
    "Coach",
    "CarrierIntegration",
    "LicensedAgent",
    "Any",
}

# Roles whose X-User-ID must be the id of an existing row of the named entity.
ENTITY_BACKED = {"LicensedAgent": ("Agent", "agents")}

NOT_FOUND_ERRORS = {
    "Agency": "ERR_AGENCY_NOT_FOUND",
    "Carrier": "ERR_CARRIER_NOT_FOUND",
    "Agent": "ERR_AGENT_NOT_FOUND",
    "Member": "ERR_MEMBER_NOT_FOUND",
    "Plan": "ERR_PLAN_NOT_FOUND",
    "ScopeOfAppointment": "ERR_SCOPE_OF_APPOINTMENT_NOT_FOUND",
    "CallSession": "ERR_CALL_SESSION_NOT_FOUND",
    "Enrollment": "ERR_ENROLLMENT_NOT_FOUND",
    "Complaint": "ERR_COMPLAINT_NOT_FOUND",
    "CoachingAssignment": "ERR_COACHING_ASSIGNMENT_NOT_FOUND",
    "CommissionLedgerEntry": "ERR_LEDGER_ENTRY_NOT_FOUND",
    "CarrierReconciliation": "ERR_RECONCILIATION_NOT_FOUND",
    "CarrierAppointment": "ERR_APPOINTMENT_NOT_FOUND",
    "AgentStateLicense": "ERR_STATE_LICENSE_NOT_FOUND",
}


def authenticate(allowed_roles):
    """Priority 1 (headers + declared role + entity-backed identity) then
    priority 2 (strict role allow-list)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role must both be present and name a declared role.",
        )
    if role in ENTITY_BACKED:
        entity_name, collection = ENTITY_BACKED[role]
        if user_id not in getattr(db, collection):
            raise ApiError(
                "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                "X-User-ID must be the id of an existing %s." % entity_name,
            )
    if role not in allowed_roles:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "The acting role is not permitted to call this endpoint.",
        )
    return user_id, role


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


def require_field(payload, name, expected=None):
    if name not in payload or payload[name] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s." % name)
    value = payload[name]
    if expected is not None and not isinstance(value, expected):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s has the wrong type." % name)
    return value


def optional(payload, name, default=None):
    value = payload.get(name)
    return default if value is None else value


def as_int(value, field):
    try:
        if isinstance(value, bool):
            raise ValueError
        return int(value)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)


def as_bool(value, field):
    if isinstance(value, bool):
        return value
    raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)


def as_instant(value, field):
    try:
        return db.parse_iso(value)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 instant." % field)


def resolve(entity_name, entity_id):
    """Path/body id resolution — the entity-specific 404 for the first miss."""
    row = serializers.get(entity_name, entity_id)
    if row is None:
        raise ApiError(NOT_FOUND_ERRORS[entity_name], "%s does not resolve." % entity_name)
    return row


def resolve_agency(agency_id):
    return resolve("Agency", agency_id)


def agency_of_agent(agent):
    return db.agencies.get(agent["agency_id"])


def gate_posture(agency, error_id="ERR_AGENCY_FROZEN"):
    """A FROZEN agency refuses every mutating child operation."""
    if agency is not None and agency["compliance_posture"] == "FROZEN":
        raise ApiError(error_id, "The agency is FROZEN; this operation is refused.")


def owner_check(role, user_id, body_agent_id):
    """A LicensedAgent acts only in their own name (PRD 2.1)."""
    if role == "LicensedAgent" and body_agent_id is not None and body_agent_id != user_id:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS",
                       "A LicensedAgent may only act for itself.")


def paginate(rows, sort_key=None):
    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", type=int)
    limit = 10 if limit is None else max(1, min(100, limit))
    offset = 0 if offset is None else max(0, offset)
    if sort_key is not None:
        rows = sorted(rows, key=sort_key)
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, limit, offset, total


def by_creation(row):
    return row["created_at"]


def text_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def bool_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value.lower() in ("true", "1", "yes")


def number_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None