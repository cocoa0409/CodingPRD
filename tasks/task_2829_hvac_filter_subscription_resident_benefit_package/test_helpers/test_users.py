"""
Identity headers for every role (PRD §2.1).

Two roles are entity-backed and therefore have no single reusable identity:

  * PropertyManager — ``X-User-ID`` must be the ``Property.id`` being acted on.
  * Resident        — ``X-User-ID`` must be the ``Resident.id`` being acted on.

Those two are produced by the per-instance builders below; using one shared
constant would make every ownership-gated call fail with
``ERR_NOT_RESOURCE_OWNER``. ProgramOperator and ClaimsAdjuster identities are
opaque strings, but a claim's triaging adjuster and deciding adjuster must be
two different ``X-User-ID`` values (segregation of duties).
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADJUSTER_ONE,
    ADJUSTER_TWO,
    OPERATOR_USER_ID,
    ROLE_CLAIMS_ADJUSTER,
    ROLE_PROGRAM_OPERATOR,
    ROLE_PROPERTY_MANAGER,
    ROLE_RESIDENT,
)

# ─── Opaque identities ────────────────────────────────────────────────────────

OPERATOR = build_user_headers(OPERATOR_USER_ID, ROLE_PROGRAM_OPERATOR)
OPERATOR_ALT = build_user_headers("op-002", ROLE_PROGRAM_OPERATOR)

ADJUSTER_A = build_user_headers(ADJUSTER_ONE, ROLE_CLAIMS_ADJUSTER)
ADJUSTER_B = build_user_headers(ADJUSTER_TWO, ROLE_CLAIMS_ADJUSTER)


# ─── Entity-backed identities ─────────────────────────────────────────────────

def make_property_manager_headers(property_id: str) -> dict:
    """PropertyManager acting on the property whose id is its X-User-ID."""
    return build_user_headers(property_id, ROLE_PROPERTY_MANAGER)


def make_resident_headers(resident_id: str) -> dict:
    """Resident acting on the resident record whose id is its X-User-ID."""
    return build_user_headers(resident_id, ROLE_RESIDENT)


def make_adjuster_headers(user_id: str) -> dict:
    """ClaimsAdjuster with an explicit opaque identity."""
    return build_user_headers(user_id, ROLE_CLAIMS_ADJUSTER)


def make_operator_headers(user_id: str = OPERATOR_USER_ID) -> dict:
    """ProgramOperator with an explicit opaque identity."""
    return build_user_headers(user_id, ROLE_PROGRAM_OPERATOR)


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary identity/role pair — used for unrecognised-role probes."""
    return build_user_headers(user_id, role)


# ─── Malformed identity headers ───────────────────────────────────────────────

def headers_without_user_id(role: str = ROLE_PROGRAM_OPERATOR) -> dict:
    """Well-formed request that omits X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = OPERATOR_USER_ID) -> dict:
    """Well-formed request that omits X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = ROLE_PROGRAM_OPERATOR) -> dict:
    """X-User-ID present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str = OPERATOR_USER_ID) -> dict:
    """X-User-Role present but empty."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


UNRECOGNISED_ROLE_HEADERS = build_user_headers("wh-001", "Warehouse")
