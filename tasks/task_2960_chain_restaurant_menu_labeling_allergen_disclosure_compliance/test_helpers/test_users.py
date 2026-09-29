"""Fixed test identities and their auth headers.

PRD 2.1 splits the five roles into two families. `PlatformAdmin` and
`NutritionAnalyst` are opaque: their `X-User-ID` is not resolved against any
row, so a stable literal suffices. `BrandComplianceOfficer`,
`MenuboardPublisher` and `StateRegulator` are entity-backed: their
`X-User-ID` must equal the `Brand.id`, `Establishment.id` or
`Jurisdiction.id` that owns the resource being written, so headers for those
roles are built per-resource by the `make_*` helpers below.

Every distinct resource owner therefore gets its own `X-User-ID`; two brands
never share an officer identity.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BRAND_COMPLIANCE_OFFICER,
    ROLE_MENUBOARD_PUBLISHER,
    ROLE_NUTRITION_ANALYST,
    ROLE_PLATFORM_ADMIN,
    ROLE_STATE_REGULATOR,
)

# --- Opaque identities -----------------------------------------------------
PLATFORM_ADMIN_USER_ID = "platform-admin-1"

# PRD 3.4 segregates duties on CERTIFY only, so the suite keeps two distinct
# analyst identities: one submits, the other certifies.
ANALYST_SUBMITTER_USER_ID = "analyst-1"
ANALYST_CERTIFIER_USER_ID = "analyst-2"
ANALYST_THIRD_USER_ID = "analyst-3"

PLATFORM_ADMIN = build_user_headers(PLATFORM_ADMIN_USER_ID, ROLE_PLATFORM_ADMIN)
ANALYST_SUBMITTER = build_user_headers(
    ANALYST_SUBMITTER_USER_ID, ROLE_NUTRITION_ANALYST
)
ANALYST_CERTIFIER = build_user_headers(
    ANALYST_CERTIFIER_USER_ID, ROLE_NUTRITION_ANALYST
)
ANALYST_THIRD = build_user_headers(ANALYST_THIRD_USER_ID, ROLE_NUTRITION_ANALYST)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": PLATFORM_ADMIN,
    "analyst_submitter": ANALYST_SUBMITTER,
    "analyst_certifier": ANALYST_CERTIFIER,
    "analyst_third": ANALYST_THIRD,
}


# --- Entity-backed identities ---------------------------------------------
def make_brand_officer_headers(brand_id: str) -> Dict[str, str]:
    """Headers for the `BrandComplianceOfficer` of one specific brand."""
    return build_user_headers(brand_id, ROLE_BRAND_COMPLIANCE_OFFICER)


def make_publisher_headers(establishment_id: str) -> Dict[str, str]:
    """Headers for the `MenuboardPublisher` of one specific unit."""
    return build_user_headers(establishment_id, ROLE_MENUBOARD_PUBLISHER)


def make_regulator_headers(jurisdiction_id: str) -> Dict[str, str]:
    """Headers for the `StateRegulator` of one specific authority."""
    return build_user_headers(jurisdiction_id, ROLE_STATE_REGULATOR)


def make_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_analyst_headers(user_id: str = ANALYST_SUBMITTER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_NUTRITION_ANALYST)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identity/role pair, for RBAC probes."""
    return build_user_headers(user_id, role)


# --- Malformed auth headers ------------------------------------------------
# PRD 2.1 distinguishes an absent or empty `X-User-ID` from an absent, empty or
# unknown `X-User-Role`. The empty cases use the empty string (never a
# whitespace-only value, which no HTTP client will transmit as a header).
def headers_without_user_id(role: str) -> Dict[str, str]:
    """Auth headers with the `X-User-ID` key omitted entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """Auth headers whose `X-User-ID` is the empty string."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Auth headers with the `X-User-Role` key omitted entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str) -> Dict[str, str]:
    """Auth headers whose `X-User-Role` is the empty string."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


UNKNOWN_ROLE = "MenuAuditor"


def headers_with_unknown_role(user_id: str) -> Dict[str, str]:
    """Auth headers naming a role that is not one of the five of PRD 2.1."""
    return build_user_headers(user_id, UNKNOWN_ROLE)
