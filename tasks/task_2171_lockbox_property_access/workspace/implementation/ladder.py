"""Shared rungs of the rejection ladder (PRD §2.6)."""
from core import fail, is_int, is_str, present

TERMINAL_STATES = {
    "lockbox": ("RETIRED",),
    "listing": ("CLOSED", "WITHDRAWN"),
    "placement": ("REMOVED",),
    "credential": ("REVOKED", "EXPIRED"),
    "grant": ("DENIED", "REVOKED", "EXPIRED", "CONSUMED"),
    "appointment": ("COMPLETED", "CANCELLED", "NO_SHOW"),
    "charge": ("PAID", "WAIVED", "VOID"),
    "member": ("TERMINATED",),
}


def require_action(payload, allowed, field="action"):
    """Rung 5 (priority 20) — the action/event_type field is present and legal."""
    if not present(payload, field) or not is_str(payload[field]):
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    value = payload[field]
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (field, ", ".join(allowed)))
    return value


def require_version_field(payload, field):
    """Rung 5 (priority 20) — the expected-version field is present and an integer."""
    if not present(payload, field) or not is_int(payload[field]):
        fail("ERR_INVALID_REQUEST", "%s is required and must be an integer." % field)
    return payload[field]


def assert_version(expected, record):
    """Rung 8 (priority 35) — optimistic concurrency."""
    if expected != record.get("version"):
        fail("ERR_STALE_VERSION", "The record has been modified since it was read.")


def assert_owner(role, user_id, owner_id):
    """Rung 6 (priority 25) — Member ownership. Admins are exempt."""
    if role == "Member" and owner_id != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The caller does not own this resource.")


def assert_not_terminal(kind, status):
    """Rung 11 (priority 45) — terminal lockdown."""
    if status in TERMINAL_STATES[kind]:
        fail("ERR_ENTITY_TERMINAL", "The entity is in a terminal state.")


def assert_transition(current, table, action):
    """Rung 9 (priority 40) — a declared transition exists for this action."""
    allowed = table.get(action)
    if not allowed or current not in allowed:
        fail("ERR_INVALID_STATE",
             "Action %s is not available from state %s." % (action, current))


def require_str(payload, field):
    if not present(payload, field) or not is_str(payload[field]) or not payload[field].strip():
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    return payload[field]
