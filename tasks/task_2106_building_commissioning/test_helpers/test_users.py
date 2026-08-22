"""Pre-built role headers for every role in the PRD.

Every one of the five roles carries an opaque identity: the `X-User-ID` is an
operator identifier that the server never resolves to a stored row.  The shared
constants below are therefore the canonical form for ordinary calls.  The
per-user builders exist for the segregation-of-duties rules, where the acting
`X-User-ID` of a later step is compared against the id recorded on an earlier
step of the same artifact.
"""

from prd_bench_local_runner.testing import build_user_headers

# Canonical operator identifiers used throughout the fixtures.
USER_IDS = {
    "platform_admin": "u-admin-1",
    "cx_authority": "u-cxa-1",
    "cx_authority_alt": "u-cxa-2",
    "cx_authority_second": "u-cxa-9",
    "contractor": "u-contractor-1",
    "contractor_alt": "u-contractor-2",
    "design_team": "u-design-1",
    "owner_representative": "u-owner-1",
}

TEST_USERS = {
    "platform_admin_headers": build_user_headers(
        USER_IDS["platform_admin"], "PlatformAdmin"
    ),
    "cx_authority_headers": build_user_headers(USER_IDS["cx_authority"], "CxAuthority"),
    "cx_authority_alt_headers": build_user_headers(
        USER_IDS["cx_authority_alt"], "CxAuthority"
    ),
    "contractor_headers": build_user_headers(USER_IDS["contractor"], "Contractor"),
    "design_team_headers": build_user_headers(USER_IDS["design_team"], "DesignTeam"),
    "owner_representative_headers": build_user_headers(
        USER_IDS["owner_representative"], "OwnerRepresentative"
    ),
}


def make_platform_admin_headers(user_id: str) -> dict:
    """Headers for a PlatformAdmin acting under a specific operator id."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_cx_authority_headers(user_id: str) -> dict:
    """Headers for a CxAuthority acting under a specific operator id."""
    return build_user_headers(user_id, "CxAuthority")


def make_contractor_headers(user_id: str) -> dict:
    """Headers for a Contractor acting under a specific operator id."""
    return build_user_headers(user_id, "Contractor")


def make_design_team_headers(user_id: str) -> dict:
    """Headers for a DesignTeam member acting under a specific operator id."""
    return build_user_headers(user_id, "DesignTeam")


def make_owner_representative_headers(user_id: str) -> dict:
    """Headers for an OwnerRepresentative acting under a specific operator id."""
    return build_user_headers(user_id, "OwnerRepresentative")


ADMIN = TEST_USERS["platform_admin_headers"]
CXA = TEST_USERS["cx_authority_headers"]
CXA_ALT = TEST_USERS["cx_authority_alt_headers"]
CONTRACTOR = TEST_USERS["contractor_headers"]
DESIGN = TEST_USERS["design_team_headers"]
OWNER = TEST_USERS["owner_representative_headers"]
