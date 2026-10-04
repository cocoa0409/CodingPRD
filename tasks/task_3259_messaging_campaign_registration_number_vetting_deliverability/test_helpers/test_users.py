"""Caller identities.

PRD section 2.1: for every role, X-User-ID is an opaque operator identifier
that the server never compares against any entity id; authorization is
decided by role membership alone. Header sets are therefore shared
constants, one per role, plus malformed variants for the 401 corners.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BRAND_MANAGER,
    ROLE_CAMPAIGN_MANAGER,
    ROLE_CARRIER_REVIEWER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DELIVERABILITY_ANALYST,
    ROLE_NUMBER_PROVISIONER,
    ROLE_PLATFORM_ADMIN,
    ROLE_SYSTEM_DRIVER,
)

# ─── Opaque operator identifiers ──────────────────────────────────────────

ADMIN_USER_ID = "admin-1"
BRAND_MANAGER_USER_ID = "brand-manager-1"
CAMPAIGN_MANAGER_USER_ID = "campaign-manager-1"
CARRIER_REVIEWER_USER_ID = "carrier-reviewer-1"
PROVISIONER_USER_ID = "provisioner-1"
COMPLIANCE_USER_ID = "compliance-1"
ANALYST_USER_ID = "analyst-1"
SYSTEM_DRIVER_USER_ID = "system-driver-1"

# ─── Ready-made header sets, one per role ─────────────────────────────────

ADMIN = build_user_headers(ADMIN_USER_ID, ROLE_PLATFORM_ADMIN)
BRAND_MANAGER = build_user_headers(BRAND_MANAGER_USER_ID, ROLE_BRAND_MANAGER)
CAMPAIGN_MANAGER = build_user_headers(
    CAMPAIGN_MANAGER_USER_ID, ROLE_CAMPAIGN_MANAGER
)
CARRIER_REVIEWER = build_user_headers(
    CARRIER_REVIEWER_USER_ID, ROLE_CARRIER_REVIEWER
)
PROVISIONER = build_user_headers(PROVISIONER_USER_ID, ROLE_NUMBER_PROVISIONER)
COMPLIANCE = build_user_headers(COMPLIANCE_USER_ID, ROLE_COMPLIANCE_OFFICER)
ANALYST = build_user_headers(ANALYST_USER_ID, ROLE_DELIVERABILITY_ANALYST)
SYSTEM_DRIVER = build_user_headers(SYSTEM_DRIVER_USER_ID, ROLE_SYSTEM_DRIVER)


def headers_for(role, user_id):
    """Arbitrary role/identity pairing."""
    return build_user_headers(user_id, role)


# ─── Malformed authentication header sets ─────────────────────────────────

MISSING_HEADERS = {"Content-Type": "application/json"}

UNKNOWN_ROLE = {
    "X-User-ID": ADMIN_USER_ID,
    "X-User-Role": "StadiumUsher",
    "Content-Type": "application/json",
}
