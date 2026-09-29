"""Auth header builders.

Four roles are operator identities: their ``X-User-ID`` is an opaque string the
server only stores as provenance. Two roles are entity-backed: ``Agency`` and
``TechnologyPartner`` must present the acting DistributionPartner's ``id``, so
those headers can only be built once the partner exists.

Blank-header cases deliberately use the empty string rather than a whitespace
string: the PRD treats a whitespace-only value exactly as an absent one, and the
HTTP client library refuses to transmit whitespace-only header values at all.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_AGENCY,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_DISTRIBUTION_MANAGER,
    ROLE_PLATFORM_ADMIN,
    ROLE_PRICING_ANALYST,
    ROLE_TECHNOLOGY_PARTNER,
)

Headers = Dict[str, str]

# --- Opaque operator identifiers -----------------------------------------
ADMIN_USER_ID = "admin-001"
PRICING_ANALYST_USER_ID = "pa-001"
DISTRIBUTION_MANAGER_USER_ID = "dm-001"
OTHER_DISTRIBUTION_MANAGER_USER_ID = "dm-002"
AUDITOR_USER_ID = "aud-001"

UNKNOWN_ROLE = "SuperUser"

ADMIN_HEADERS: Headers = build_user_headers(ADMIN_USER_ID, ROLE_PLATFORM_ADMIN)
PRICING_ANALYST_HEADERS: Headers = build_user_headers(
    PRICING_ANALYST_USER_ID, ROLE_PRICING_ANALYST
)
DISTRIBUTION_MANAGER_HEADERS: Headers = build_user_headers(
    DISTRIBUTION_MANAGER_USER_ID, ROLE_DISTRIBUTION_MANAGER
)
OTHER_DISTRIBUTION_MANAGER_HEADERS: Headers = build_user_headers(
    OTHER_DISTRIBUTION_MANAGER_USER_ID, ROLE_DISTRIBUTION_MANAGER
)
AUDITOR_HEADERS: Headers = build_user_headers(AUDITOR_USER_ID, ROLE_COMPLIANCE_AUDITOR)

TEST_USERS: Dict[str, Headers] = {
    ROLE_PLATFORM_ADMIN: ADMIN_HEADERS,
    ROLE_PRICING_ANALYST: PRICING_ANALYST_HEADERS,
    ROLE_DISTRIBUTION_MANAGER: DISTRIBUTION_MANAGER_HEADERS,
    ROLE_COMPLIANCE_AUDITOR: AUDITOR_HEADERS,
}


def agency_headers(partner_id: str) -> Headers:
    """Headers for an Agency acting as the DistributionPartner ``partner_id``."""
    return build_user_headers(partner_id, ROLE_AGENCY)


def technology_partner_headers(partner_id: str) -> Headers:
    """Headers for a TechnologyPartner acting as the partner ``partner_id``."""
    return build_user_headers(partner_id, ROLE_TECHNOLOGY_PARTNER)


def headers_for_role(role: str, partner_id: str = "") -> Headers:
    """Headers for any of the six roles; entity-backed roles need ``partner_id``."""
    if role == ROLE_AGENCY:
        return agency_headers(partner_id)
    if role == ROLE_TECHNOLOGY_PARTNER:
        return technology_partner_headers(partner_id)
    return TEST_USERS[role]


def headers_missing_user_id(role: str = ROLE_PLATFORM_ADMIN) -> Headers:
    """Headers with no ``X-User-ID`` at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str = ADMIN_USER_ID) -> Headers:
    """Headers with no ``X-User-Role`` at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_empty_user_id(role: str = ROLE_PLATFORM_ADMIN) -> Headers:
    """Headers whose ``X-User-ID`` is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_empty_role(user_id: str = ADMIN_USER_ID) -> Headers:
    """Headers whose ``X-User-Role`` is present but empty."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_unknown_role(user_id: str = ADMIN_USER_ID, role: str = UNKNOWN_ROLE) -> Headers:
    """Headers naming a role outside the six the PRD declares."""
    return build_user_headers(user_id, role)
