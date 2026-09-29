"""
Caller identities.

Four of the six roles are opaque operator identities: any stable token works, so
this module hands out named constants and pre-built header dicts for them.

The other two roles are entity-backed. A `CertifiedInstaller`'s `X-User-ID` must be
the `id` of a real `InstallerAccount` row and a `Homeowner`'s must be the `id` of a
real `Site` row, so their headers cannot be constants — they are built per test from
the id the fixture just created, via `make_installer_headers` / `make_homeowner_headers`.
Reaching for a shared constant instead is what turns one ownership check into a
cascade of unexplained 403s.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ── Opaque operator identities ───────────────────────
AHJ_USER_ID = "ahj-user-1"
AHJ_USER_2_ID = "ahj-user-2"
UTILITY_REVIEWER_ID = "utility-rev-1"
UTILITY_REVIEWER_2_ID = "utility-rev-2"
REBATE_ADMIN_ID = "rebate-admin-1"
REBATE_ADMIN_2_ID = "rebate-admin-2"
WARRANTY_AGENT_ID = "mfg-agent-1"
WARRANTY_AGENT_2_ID = "mfg-agent-2"

# A syntactically valid but unregistered installer/site id, for ownership probes
# that need a caller who exists as a header but owns nothing.
UNKNOWN_ENTITY_ID = "11111111-1111-1111-1111-111111111111"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "ahj": {"user_id": AHJ_USER_ID, "role": UserRole.AUTHORITY_HAVING_JURISDICTION},
    "ahj_2": {"user_id": AHJ_USER_2_ID, "role": UserRole.AUTHORITY_HAVING_JURISDICTION},
    "utility_reviewer": {
        "user_id": UTILITY_REVIEWER_ID,
        "role": UserRole.UTILITY_INTERCONNECTION_REVIEWER,
    },
    "utility_reviewer_2": {
        "user_id": UTILITY_REVIEWER_2_ID,
        "role": UserRole.UTILITY_INTERCONNECTION_REVIEWER,
    },
    "rebate_admin": {"user_id": REBATE_ADMIN_ID, "role": UserRole.REBATE_ADMINISTRATOR},
    "rebate_admin_2": {
        "user_id": REBATE_ADMIN_2_ID,
        "role": UserRole.REBATE_ADMINISTRATOR,
    },
    "warranty_agent": {
        "user_id": WARRANTY_AGENT_ID,
        "role": UserRole.MANUFACTURER_WARRANTY_AGENT,
    },
    "warranty_agent_2": {
        "user_id": WARRANTY_AGENT_2_ID,
        "role": UserRole.MANUFACTURER_WARRANTY_AGENT,
    },
}


# Pre-built headers for the opaque roles.
AHJ_HEADERS = build_user_headers(AHJ_USER_ID, UserRole.AUTHORITY_HAVING_JURISDICTION)
AHJ_2_HEADERS = build_user_headers(
    AHJ_USER_2_ID, UserRole.AUTHORITY_HAVING_JURISDICTION
)
UTILITY_REVIEWER_HEADERS = build_user_headers(
    UTILITY_REVIEWER_ID, UserRole.UTILITY_INTERCONNECTION_REVIEWER
)
UTILITY_REVIEWER_2_HEADERS = build_user_headers(
    UTILITY_REVIEWER_2_ID, UserRole.UTILITY_INTERCONNECTION_REVIEWER
)
REBATE_ADMIN_HEADERS = build_user_headers(
    REBATE_ADMIN_ID, UserRole.REBATE_ADMINISTRATOR
)
REBATE_ADMIN_2_HEADERS = build_user_headers(
    REBATE_ADMIN_2_ID, UserRole.REBATE_ADMINISTRATOR
)
WARRANTY_AGENT_HEADERS = build_user_headers(
    WARRANTY_AGENT_ID, UserRole.MANUFACTURER_WARRANTY_AGENT
)
WARRANTY_AGENT_2_HEADERS = build_user_headers(
    WARRANTY_AGENT_2_ID, UserRole.MANUFACTURER_WARRANTY_AGENT
)


def headers_for(user_key: str) -> Dict[str, str]:
    """Headers for one of the named opaque operators, by key of TEST_USERS."""
    user = TEST_USERS[user_key]
    return build_user_headers(user["user_id"], user["role"])


def make_installer_headers(installer_id: str) -> Dict[str, str]:
    """Headers for the installation company whose InstallerAccount id is given."""
    return build_user_headers(installer_id, UserRole.CERTIFIED_INSTALLER)


def make_homeowner_headers(site_id: str) -> Dict[str, str]:
    """Headers for the household whose Site id is given."""
    return build_user_headers(site_id, UserRole.HOMEOWNER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary caller, for probes that need an unusual pairing."""
    return build_user_headers(user_id, role)
