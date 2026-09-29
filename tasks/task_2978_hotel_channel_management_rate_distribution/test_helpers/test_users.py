"""Caller identities and the header pairs that carry them.

Every request presents both ``X-User-ID`` and ``X-User-Role``. Four of the five
roles are staff roles whose identifier is an opaque caller identifier; the fifth
is entity-backed, so its identifier must be the identifier of an existing
channel and its headers are built per channel at call time.

The two-person rule on promotion approval means the submitting identifier and
the approving identifier must differ, so several distinct identifiers exist per
staff role rather than one shared identifier.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CHANNEL_OPS_ENGINEER,
    ROLE_CHANNEL_PARTNER,
    ROLE_PLATFORM_ADMIN,
    ROLE_REVENUE_DIRECTOR,
    ROLE_REVENUE_MANAGER,
)

# ── Caller identifiers ─────────────────────────────────────────────────────

TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": {
        "user_id": "a1f0c2d4-5e6b-4a71-8c93-0d1e2f3a4b50",
        "role": ROLE_PLATFORM_ADMIN,
    },
    "revenue_manager": {
        "user_id": "b2e1d3c5-6f7a-4b82-9da4-1e2f3a4b5c61",
        "role": ROLE_REVENUE_MANAGER,
    },
    "revenue_manager_alt": {
        "user_id": "c3d2e4b6-7a8b-4c93-8eb5-2f3a4b5c6d72",
        "role": ROLE_REVENUE_MANAGER,
    },
    "revenue_director": {
        "user_id": "d4c3f5a7-8b9c-4da4-9fc6-3a4b5c6d7e83",
        "role": ROLE_REVENUE_DIRECTOR,
    },
    "revenue_director_alt": {
        "user_id": "e5b4a6c8-9cad-4eb5-8ad7-4b5c6d7e8f94",
        "role": ROLE_REVENUE_DIRECTOR,
    },
    "channel_ops_engineer": {
        "user_id": "f6a5b7d9-adbe-4fc6-9be8-5c6d7e8f90a5",
        "role": ROLE_CHANNEL_OPS_ENGINEER,
    },
}

# ── Ready-made header pairs for the staff roles ────────────────────────────

PLATFORM_ADMIN_HEADERS: Dict[str, str] = build_user_headers(
    TEST_USERS["platform_admin"]["user_id"], TEST_USERS["platform_admin"]["role"]
)

REVENUE_MANAGER_HEADERS: Dict[str, str] = build_user_headers(
    TEST_USERS["revenue_manager"]["user_id"], TEST_USERS["revenue_manager"]["role"]
)

REVENUE_MANAGER_ALT_HEADERS: Dict[str, str] = build_user_headers(
    TEST_USERS["revenue_manager_alt"]["user_id"], TEST_USERS["revenue_manager_alt"]["role"]
)

REVENUE_DIRECTOR_HEADERS: Dict[str, str] = build_user_headers(
    TEST_USERS["revenue_director"]["user_id"], TEST_USERS["revenue_director"]["role"]
)

REVENUE_DIRECTOR_ALT_HEADERS: Dict[str, str] = build_user_headers(
    TEST_USERS["revenue_director_alt"]["user_id"], TEST_USERS["revenue_director_alt"]["role"]
)

CHANNEL_OPS_ENGINEER_HEADERS: Dict[str, str] = build_user_headers(
    TEST_USERS["channel_ops_engineer"]["user_id"], TEST_USERS["channel_ops_engineer"]["role"]
)

# The identifier a submission is attributed to, and a different identifier that
# may therefore act on that submission.
SUBMITTER_USER_ID: str = TEST_USERS["revenue_manager"]["user_id"]
APPROVER_USER_ID: str = TEST_USERS["revenue_director"]["user_id"]


# ── Builders ───────────────────────────────────────────────────────────────


def make_platform_admin_headers() -> Dict[str, str]:
    return dict(PLATFORM_ADMIN_HEADERS)


def make_revenue_manager_headers(user_id: str = SUBMITTER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_REVENUE_MANAGER)


def make_revenue_director_headers(user_id: str = APPROVER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_REVENUE_DIRECTOR)


def make_channel_ops_engineer_headers(
    user_id: str = TEST_USERS["channel_ops_engineer"]["user_id"],
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CHANNEL_OPS_ENGINEER)


def make_channel_partner_headers(channel_id: str) -> Dict[str, str]:
    """Headers for the entity-backed role, whose identifier is a channel's own."""
    return build_user_headers(channel_id, ROLE_CHANNEL_PARTNER)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role/identifier pair."""
    return build_user_headers(user_id, role)


# ── Malformed credentials ──────────────────────────────────────────────────

# A role string that is not one of the declared five.
UNDECLARED_ROLE = "DistributionAnalyst"


def headers_without_role(user_id: str = SUBMITTER_USER_ID) -> Dict[str, str]:
    """Only the identifier header is present."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_REVENUE_MANAGER) -> Dict[str, str]:
    """Only the role header is present."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_credentials() -> Dict[str, str]:
    """Neither credential header is present."""
    return {"Content-Type": "application/json"}


def headers_with_empty_role(user_id: str = SUBMITTER_USER_ID) -> Dict[str, str]:
    """The role header is present but its value is empty.

    The value is the empty string, never a blank-looking string of spaces: a
    space would be a present, non-empty value.
    """
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = ROLE_REVENUE_MANAGER) -> Dict[str, str]:
    """The identifier header is present but its value is empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_undeclared_role(user_id: str = SUBMITTER_USER_ID) -> Dict[str, str]:
    """A syntactically fine role header naming a role that does not exist."""
    return build_user_headers(user_id, UNDECLARED_ROLE)
