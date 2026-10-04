"""Caller identities for the four declared roles.

Every request carries an ``X-User-ID`` and an ``X-User-Role`` header. Three
roles are opaque: the server never compares their ``X-User-ID`` against a
persisted entity, but it does record it - a FlowManager's id lands in
``proposed_by_user_id`` and a CommandCenterAdmin's in ``published_by_user_id``
- so those two roles also get per-call builders for tests that steer the
segregation-of-duties rule (the default proposer ``fm-1`` and publisher
``cc-1`` differ, so the default path always satisfies the rule).

The Operator role is entity-backed: its ``X-User-ID`` must equal the id of the
Operator row it acts as, so fixtures and tests MUST call
``make_operator_headers(operator["id"])`` for every ownership-gated write.
Falling back to a shared constant would make every ownership check reject the
call.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMMAND_CENTER_ADMIN,
    ROLE_FLOW_MANAGER,
    ROLE_OPERATOR,
    ROLE_SYSTEM_ADMINISTRATOR,
)

# Opaque identifiers for the roles that are not matched against an entity row.
# "fm-1" / "cc-1" are the ids the design recipes' segregation-of-duties flows
# are written against.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "system_admin": {"id": "sa-1", "role": ROLE_SYSTEM_ADMINISTRATOR},
    "flow_manager": {"id": "fm-1", "role": ROLE_FLOW_MANAGER},
    "command_center_admin": {"id": "cc-1", "role": ROLE_COMMAND_CENTER_ADMIN},
    # Fallback for the entity-backed Operator role; safe ONLY where ownership
    # is not exercised (malformed-body or not-found probes). Real calls use
    # make_operator_headers(operator_id).
    "operator": {"id": "op-standalone", "role": ROLE_OPERATOR},
}

SYSTEM_ADMIN_HEADERS = build_user_headers(
    TEST_USERS["system_admin"]["id"], ROLE_SYSTEM_ADMINISTRATOR
)
FLOW_MANAGER_HEADERS = build_user_headers(
    TEST_USERS["flow_manager"]["id"], ROLE_FLOW_MANAGER
)
COMMAND_CENTER_HEADERS = build_user_headers(
    TEST_USERS["command_center_admin"]["id"], ROLE_COMMAND_CENTER_ADMIN
)
OPERATOR_HEADERS = build_user_headers(TEST_USERS["operator"]["id"], ROLE_OPERATOR)


# ── Per-instance builders ──────────────────────────────────────────────────

def make_flow_manager_headers(user_id: str) -> Dict[str, str]:
    """Headers for a FlowManager; the id is recorded as proposed_by_user_id."""
    return build_user_headers(user_id, ROLE_FLOW_MANAGER)


def make_command_center_headers(user_id: str) -> Dict[str, str]:
    """Headers for a CommandCenterAdmin; pass the proposer's id to exercise the
    segregation-of-duties rejection."""
    return build_user_headers(user_id, ROLE_COMMAND_CENTER_ADMIN)


def make_operator_headers(operator_id: str) -> Dict[str, str]:
    """Headers for an Operator acting as the given Operator row. Pass the real
    operator's id for every ownership-gated write."""
    return build_user_headers(operator_id, ROLE_OPERATOR)


# ── Malformed credentials, for the authentication tier ─────────────────────

def headers_without_role(user_id: str = "sa-1") -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_SYSTEM_ADMINISTRATOR) -> Dict[str, str]:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str = "sa-1") -> Dict[str, str]:
    """Headers whose X-User-Role is the empty string."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_with_undeclared_role(user_id: str = "sa-1") -> Dict[str, str]:
    """Headers whose X-User-Role is not one of the four declared roles."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "AirTrafficController",
        "Content-Type": "application/json",
    }
