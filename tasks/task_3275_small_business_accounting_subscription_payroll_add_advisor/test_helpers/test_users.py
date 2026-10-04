"""Caller identities.

The PRD's role model:
- PlatformAdmin: X-User-ID is opaque; not tied to any persisted entity.
- CompanyUser: X-User-ID is the id of the persisted CompanyUser row.
- AccountantUser: X-User-ID is the id of the persisted AccountantUser row.

For entity-backed roles the suite builds headers via ``make_company_user_headers``
/ ``make_accountant_user_headers`` with the entity's actual id.  Shared
constants exist for PlatformAdmin (opaque) and as a fallback for tests that
don't exercise ownership.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ACCOUNTANT_USER,
    ROLE_COMPANY_USER,
    ROLE_PLATFORM_ADMIN,
)

PLATFORM_ADMIN_USER_ID = "platform-admin-1"

# --- Ready-made header sets ----------------------------------------------------

TEST_USERS = {
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_USER_ID, ROLE_PLATFORM_ADMIN
    ),
    # Fallback constants — only for tests whose outcome does NOT depend on the
    # caller being the persisted entity (e.g. existence checks, not-found tests).
    "company_user_headers": build_user_headers("company-user-fallback", ROLE_COMPANY_USER),
    "accountant_user_headers": build_user_headers(
        "accountant-user-fallback", ROLE_ACCOUNTANT_USER
    ),
}

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
COMPANY_USER_FALLBACK = TEST_USERS["company_user_headers"]
ACCOUNTANT_USER_FALLBACK = TEST_USERS["accountant_user_headers"]


# --- Per-instance builders (mandatory for entity-backed roles) --------------------


def make_company_user_headers(user_id):
    """For CompanyUser (entity_backed:CompanyUser).  Pass the actual
    CompanyUser.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, ROLE_COMPANY_USER)


def make_accountant_user_headers(user_id):
    """For AccountantUser (entity_backed:AccountantUser).  Pass the actual
    AccountantUser.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, ROLE_ACCOUNTANT_USER)


def make_platform_admin_headers(user_id=PLATFORM_ADMIN_USER_ID):
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


# --- Malformed / absent header sets ------------------------------------------------

NO_HEADERS = {}
MISSING_ROLE_HEADERS = {"X-User-ID": "mystery-user"}
MISSING_ID_HEADERS = {"X-User-Role": ROLE_PLATFORM_ADMIN}
