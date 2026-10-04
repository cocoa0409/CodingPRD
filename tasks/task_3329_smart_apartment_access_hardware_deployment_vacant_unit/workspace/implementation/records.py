"""Common resource properties (PRD 2.4) and request-body validation (PRD 2.12)."""

from flask import request

from db import (  # noqa: F401  (re-exported for callers)
    INTERNAL_PREFIX,
    clock,
    iso,
    new_id,
    new_record,
    serialize,
    serialize_all,
    touch,
)
from errors import ERR_INVALID_REQUEST, ApiError

# Fields the server derives; supplying one is an unknown-field rejection
# under the well-formedness check (PRD 2.4, 2.12).
NEVER_ACCEPTED = {
    "id",
    "created_at",
    "updated_at",
    "version",
    "connectivity_ok",
    "budget_committed_cents",
    "occupancy_status",
    "target_setpoint_c",
    "hvac_mode",
    "unauthorized_entry_detected",
    "battery_pct",
    "status",
    "lock_state",
    "battery_replacements",
    "severity",
    "battery_replaced",
    "planned_hours",
    "actual_hours",
    "accrued_cost_cents",
    "labor_hours",
    "portal_credential_status",
    "valid_until",
    "identity_verified_at",
    "verify_attempts",
    "recorded_at",
}


# ---------------------------------------------------------------------------
# Request-body handling
# ---------------------------------------------------------------------------
def body():
    raw = request.get_json(silent=True)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return raw


def validate_body(payload, required=(), optional=(), allow=()):
    """Priority 3: required fields present, no unknown field, no computed input."""
    allowed = set(required) | set(optional) | set(allow)
    for name in required:
        if name not in payload:
            raise ApiError(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    for name in payload:
        if name not in allowed:
            if name in NEVER_ACCEPTED:
                raise ApiError(
                    ERR_INVALID_REQUEST,
                    "Field %s is server-computed and cannot be supplied" % name,
                )
            raise ApiError(ERR_INVALID_REQUEST, "Unknown field: %s" % name)
    return payload


def require_value(payload, name):
    value = payload.get(name)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    return value


def optional_bool(payload, name, default=False):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a boolean" % name)
    return value