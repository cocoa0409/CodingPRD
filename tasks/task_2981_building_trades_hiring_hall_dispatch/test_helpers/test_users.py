"""
Auth headers for the five roles of §2.1.

Three roles are opaque: `HallAdmin`, `Dispatcher` and `BusinessManager` carry an
operator identifier the server never compares to any entity id, so a fixed
constant is enough. Two roles are entity-backed: a `ContractorRep`'s
`X-User-ID` is the acting `Contractor.id` and a `Member`'s is the acting
`Member.id`, so those two roles get per-instance builders that must be threaded
with the real id minted during setup — otherwise every ownership-gated call
would answer `ERR_NOT_RESOURCE_OWNER`.

Header defect builders are also here. A "blank" header sends the empty string,
never a whitespace string, because a whitespace value would be rejected by the
HTTP client before it ever reached the API under test.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BUSINESS_MANAGER,
    ROLE_CONTRACTOR_REP,
    ROLE_DISPATCHER,
    ROLE_HALL_ADMIN,
    ROLE_MEMBER,
)

# ─── Opaque operator identifiers (§2.1) ───────────────────────────────────────

HALL_ADMIN_USER_ID = "admin-01"
DISPATCHER_USER_ID = "disp-01"
OTHER_DISPATCHER_USER_ID = "disp-07"
BUSINESS_MANAGER_USER_ID = "bm-09"
OTHER_BUSINESS_MANAGER_USER_ID = "bm-01"

TEST_USERS = {
    "hall_admin": {"user_id": HALL_ADMIN_USER_ID, "role": ROLE_HALL_ADMIN},
    "dispatcher": {"user_id": DISPATCHER_USER_ID, "role": ROLE_DISPATCHER},
    "other_dispatcher": {"user_id": OTHER_DISPATCHER_USER_ID, "role": ROLE_DISPATCHER},
    "business_manager": {
        "user_id": BUSINESS_MANAGER_USER_ID,
        "role": ROLE_BUSINESS_MANAGER,
    },
    "other_business_manager": {
        "user_id": OTHER_BUSINESS_MANAGER_USER_ID,
        "role": ROLE_BUSINESS_MANAGER,
    },
}

# ─── Shared header dicts for the three opaque roles ───────────────────────────

HALL_ADMIN = build_user_headers(HALL_ADMIN_USER_ID, ROLE_HALL_ADMIN)
DISPATCHER = build_user_headers(DISPATCHER_USER_ID, ROLE_DISPATCHER)
OTHER_DISPATCHER = build_user_headers(OTHER_DISPATCHER_USER_ID, ROLE_DISPATCHER)
BUSINESS_MANAGER = build_user_headers(BUSINESS_MANAGER_USER_ID, ROLE_BUSINESS_MANAGER)
OTHER_BUSINESS_MANAGER = build_user_headers(
    OTHER_BUSINESS_MANAGER_USER_ID, ROLE_BUSINESS_MANAGER
)


# ─── Per-instance builders ────────────────────────────────────────────────────


def make_hall_admin_headers(user_id: str = HALL_ADMIN_USER_ID) -> Dict[str, str]:
    """`HallAdmin` is opaque; the id is an operator handle, not an entity key."""
    return build_user_headers(user_id, ROLE_HALL_ADMIN)


def make_dispatcher_headers(user_id: str = DISPATCHER_USER_ID) -> Dict[str, str]:
    """The dispatcher's id is recorded as `Referral.issued_by_user_id`."""
    return build_user_headers(user_id, ROLE_DISPATCHER)


def make_business_manager_headers(
    user_id: str = BUSINESS_MANAGER_USER_ID,
) -> Dict[str, str]:
    """The manager's id is recorded as `Grievance.decided_by_user_id`."""
    return build_user_headers(user_id, ROLE_BUSINESS_MANAGER)


def make_contractor_rep_headers(contractor_id: str) -> Dict[str, str]:
    """Entity-backed: `X-User-ID` must be the acting `Contractor.id`."""
    return build_user_headers(contractor_id, ROLE_CONTRACTOR_REP)


def make_member_headers(member_id: str) -> Dict[str, str]:
    """Entity-backed: `X-User-ID` must be the acting `Member.id`."""
    return build_user_headers(member_id, ROLE_MEMBER)


# ─── Header defects that §2.7 priority 1 must catch ───────────────────────────


def headers_missing_role(user_id: str = HALL_ADMIN_USER_ID) -> Dict[str, str]:
    """`X-User-Role` absent altogether."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_blank_role(user_id: str = HALL_ADMIN_USER_ID) -> Dict[str, str]:
    """`X-User-Role` present but empty — the empty string, not whitespace."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_unknown_role(
    user_id: str = HALL_ADMIN_USER_ID, role: str = "HiringHallClerk"
) -> Dict[str, str]:
    """A role string outside the five §2.1 names."""
    return build_user_headers(user_id, role)


def headers_missing_user_id(role: str = ROLE_HALL_ADMIN) -> Dict[str, str]:
    """`X-User-ID` absent altogether."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_blank_user_id(role: str = ROLE_MEMBER) -> Dict[str, str]:
    """`X-User-ID` present but empty — the empty string, not whitespace."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }
