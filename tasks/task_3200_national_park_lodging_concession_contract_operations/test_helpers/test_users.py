"""Caller identities.

PRD section 2.1 declares that, for every role, ``X-User-ID`` is an opaque
operator identifier that the server records for audit and for
segregation-of-duties comparisons, but never compares against a resource
``id``.  All role headers are therefore shared constants.  Two
segregation-of-duties gates (filing approval, report acceptance) compare
``X-User-ID`` values, so each adjudicating role gets at least two distinct
identities.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ACCOUNTANT,
    ROLE_CONTRACTING_OFFICER,
    ROLE_ENVIRONMENTAL_INSPECTOR,
    ROLE_FINANCIAL_AUDITOR,
    ROLE_FRONT_DESK,
    ROLE_HR_MANAGER,
    ROLE_MAINTENANCE_CHIEF,
    ROLE_OPS_MANAGER,
    ROLE_RATE_ANALYST,
    ROLE_RATE_MANAGER,
    ROLE_TEST_HARNESS,
)

# --- Opaque operator identifiers -------------------------------------------

OFFICER_USER_ID = "officer-1"
RATE_ANALYST_USER_ID = "rate-analyst-1"
RATE_ANALYST_2_USER_ID = "rate-analyst-2"
RATE_MANAGER_USER_ID = "rate-manager-1"
RATE_MANAGER_2_USER_ID = "rate-manager-2"
OPS_MANAGER_USER_ID = "ops-manager-1"
FRONT_DESK_USER_ID = "front-desk-1"
ACCOUNTANT_USER_ID = "accountant-jane"
ACCOUNTANT_2_USER_ID = "accountant-2"
AUDITOR_USER_ID = "auditor-max"
AUDITOR_2_USER_ID = "auditor-2"
MAINTENANCE_CHIEF_USER_ID = "maint-chief-1"
HR_MANAGER_USER_ID = "hr-manager-1"
INSPECTOR_USER_ID = "inspector-1"
HARNESS_USER_ID = "test-harness-1"

# --- Ready-made header sets -------------------------------------------------

TEST_USERS = {
    "contracting_officer_headers": build_user_headers(
        OFFICER_USER_ID, ROLE_CONTRACTING_OFFICER
    ),
    "rate_analyst_headers": build_user_headers(
        RATE_ANALYST_USER_ID, ROLE_RATE_ANALYST
    ),
    "rate_analyst_2_headers": build_user_headers(
        RATE_ANALYST_2_USER_ID, ROLE_RATE_ANALYST
    ),
    "rate_manager_headers": build_user_headers(
        RATE_MANAGER_USER_ID, ROLE_RATE_MANAGER
    ),
    "rate_manager_2_headers": build_user_headers(
        RATE_MANAGER_2_USER_ID, ROLE_RATE_MANAGER
    ),
    "ops_manager_headers": build_user_headers(OPS_MANAGER_USER_ID, ROLE_OPS_MANAGER),
    "front_desk_headers": build_user_headers(FRONT_DESK_USER_ID, ROLE_FRONT_DESK),
    "accountant_headers": build_user_headers(ACCOUNTANT_USER_ID, ROLE_ACCOUNTANT),
    "accountant_2_headers": build_user_headers(ACCOUNTANT_2_USER_ID, ROLE_ACCOUNTANT),
    "auditor_headers": build_user_headers(AUDITOR_USER_ID, ROLE_FINANCIAL_AUDITOR),
    "auditor_2_headers": build_user_headers(AUDITOR_2_USER_ID, ROLE_FINANCIAL_AUDITOR),
    "maintenance_chief_headers": build_user_headers(
        MAINTENANCE_CHIEF_USER_ID, ROLE_MAINTENANCE_CHIEF
    ),
    "hr_manager_headers": build_user_headers(HR_MANAGER_USER_ID, ROLE_HR_MANAGER),
    "inspector_headers": build_user_headers(
        INSPECTOR_USER_ID, ROLE_ENVIRONMENTAL_INSPECTOR
    ),
    "harness_headers": build_user_headers(HARNESS_USER_ID, ROLE_TEST_HARNESS),
}

# Convenient aliases used throughout the suite.
OFFICER = TEST_USERS["contracting_officer_headers"]
RATE_ANALYST = TEST_USERS["rate_analyst_headers"]
RATE_ANALYST_2 = TEST_USERS["rate_analyst_2_headers"]
RATE_MANAGER = TEST_USERS["rate_manager_headers"]
RATE_MANAGER_2 = TEST_USERS["rate_manager_2_headers"]
OPS_MANAGER = TEST_USERS["ops_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]
ACCOUNTANT_2 = TEST_USERS["accountant_2_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
AUDITOR_2 = TEST_USERS["auditor_2_headers"]
MAINTENANCE_CHIEF = TEST_USERS["maintenance_chief_headers"]
HR_MANAGER = TEST_USERS["hr_manager_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
HARNESS = TEST_USERS["harness_headers"]


def headers_for(role, user_id):
    """Arbitrary role/identity pairing, including deliberate cross-wirings."""
    return build_user_headers(user_id, role)


# --- Malformed / absent authentication header sets --------------------------

NO_HEADERS = {}
MISSING_ROLE_HEADERS = {"X-User-ID": "mystery-user"}
MISSING_ID_HEADERS = {"X-User-Role": ROLE_CONTRACTING_OFFICER}
UNKNOWN_ROLE_HEADERS = build_user_headers("mystery-user", "NightAuditor")
