"""Actor identities and the header builders that project them onto requests.

Two of the five roles are backed by persisted rows: a ``Member`` actor's
identifier is the id of a ``Member`` and a ``WarehouseTech`` actor's identifier
is the id of a ``Technician``.  Those two therefore have per-instance builders
that take the freshly minted row id.  The remaining three roles carry opaque
operator identifiers that resolve to nothing, so they can be shared constants.

Every distinct actor gets a distinct identifier: no two owners in a scenario
ever send the same ``X-User-ID``.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from test_helpers.constants import (
    ACTOR_CLAIMS_ADJUSTER,
    ACTOR_INVENTORY_PLANNER,
    ACTOR_PLATFORM_ADMIN,
    BLANK_ROLE,
    HEADER_USER_ID,
    HEADER_USER_ROLE,
    ROLE_CLAIMS_ADJUSTER,
    ROLE_INVENTORY_PLANNER,
    ROLE_MEMBER,
    ROLE_PLATFORM_ADMIN,
    ROLE_WAREHOUSE_TECH,
    UNDECLARED_ROLE,
    UNKNOWN_UUID,
)

Headers = Dict[str, str]

# ---------------------------------------------------------------------------
# The shared actor table.  The two entity-backed roles hold a placeholder
# identifier that a test must replace with a real row id via the builders
# below; the three opaque roles are usable as they stand.
# ---------------------------------------------------------------------------

TEST_USERS: Dict[str, Dict[str, str]] = {
    "member": {
        "user_id": UNKNOWN_UUID,
        "role": ROLE_MEMBER,
        "description": "Subscriber; entity-backed, so the id must be a real Member id",
    },
    "warehouse_tech": {
        "user_id": UNKNOWN_UUID,
        "role": ROLE_WAREHOUSE_TECH,
        "description": "Reverse-logistics operator; entity-backed by a Technician row",
    },
    "claims_adjuster": {
        "user_id": ACTOR_CLAIMS_ADJUSTER,
        "role": ROLE_CLAIMS_ADJUSTER,
        "description": "Damage adjudicator; opaque operator identifier",
    },
    "inventory_planner": {
        "user_id": ACTOR_INVENTORY_PLANNER,
        "role": ROLE_INVENTORY_PLANNER,
        "description": "Merchandising and asset owner; opaque operator identifier",
    },
    "platform_admin": {
        "user_id": ACTOR_PLATFORM_ADMIN,
        "role": ROLE_PLATFORM_ADMIN,
        "description": "Provisioning and clock driver; opaque operator identifier",
    },
}


# ---------------------------------------------------------------------------
# Per-instance builders for the entity-backed roles
# ---------------------------------------------------------------------------


def make_member_headers(member_id: str) -> Headers:
    """Headers for a specific subscriber, identified by their Member row id."""
    return build_user_headers(member_id, ROLE_MEMBER)


def make_warehouse_tech_headers(technician_id: str) -> Headers:
    """Headers for a specific technician, identified by their Technician row id."""
    return build_user_headers(technician_id, ROLE_WAREHOUSE_TECH)


# ---------------------------------------------------------------------------
# Builders for the three opaque roles
# ---------------------------------------------------------------------------


def make_claims_adjuster_headers(actor_id: str = ACTOR_CLAIMS_ADJUSTER) -> Headers:
    return build_user_headers(actor_id, ROLE_CLAIMS_ADJUSTER)


def make_inventory_planner_headers(actor_id: str = ACTOR_INVENTORY_PLANNER) -> Headers:
    return build_user_headers(actor_id, ROLE_INVENTORY_PLANNER)


def make_platform_admin_headers(actor_id: str = ACTOR_PLATFORM_ADMIN) -> Headers:
    return build_user_headers(actor_id, ROLE_PLATFORM_ADMIN)


def make_headers(user_id: str, role: str) -> Headers:
    """Headers for an arbitrary identifier/role pair."""
    return build_user_headers(user_id, role)


# ---------------------------------------------------------------------------
# Deliberately malformed header sets
# ---------------------------------------------------------------------------


def headers_with_blank_role(user_id: str) -> Headers:
    """A present-but-empty role header; the value is the empty string, not a space."""
    return {
        HEADER_USER_ID: user_id,
        HEADER_USER_ROLE: BLANK_ROLE,
        "Content-Type": "application/json",
    }


def headers_with_blank_user_id(role: str) -> Headers:
    """A present-but-empty actor header; the value is the empty string, not a space."""
    return {
        HEADER_USER_ID: "",
        HEADER_USER_ROLE: role,
        "Content-Type": "application/json",
    }


def headers_with_undeclared_role(user_id: str) -> Headers:
    """A role header naming a capability set the service does not declare."""
    return build_user_headers(user_id, UNDECLARED_ROLE)


def headers_missing_role(user_id: str) -> Headers:
    """Only the actor header is sent; the role header is absent entirely."""
    return {HEADER_USER_ID: user_id, "Content-Type": "application/json"}


def headers_missing_user_id(role: str) -> Headers:
    """Only the role header is sent; the actor header is absent entirely."""
    return {HEADER_USER_ROLE: role, "Content-Type": "application/json"}
