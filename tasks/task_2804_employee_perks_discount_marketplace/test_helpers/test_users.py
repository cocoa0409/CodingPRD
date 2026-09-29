"""Identity headers for the five roles of PRD §2.1.

`PlatformAdmin` and `PartnerManager` are opaque: their `X-User-ID` never has
to match any row, so a fixed constant is enough.  `Merchant`, `EmployerAdmin`
and `Employee` are entity-backed: the `X-User-ID` must be the id of the acting
merchant row, employer row or membership row respectively, so headers for
those roles must be built per fixture from the id that was just created.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

PLATFORM_ADMIN_ID = "admin-001"
PARTNER_MANAGER_ID = "pm-001"

TEST_USERS = {
    "platform_admin": {"user_id": PLATFORM_ADMIN_ID, "role": UserRole.PLATFORM_ADMIN},
    "partner_manager": {"user_id": PARTNER_MANAGER_ID, "role": UserRole.PARTNER_MANAGER},
}

ADMIN_HEADERS = build_user_headers(PLATFORM_ADMIN_ID, UserRole.PLATFORM_ADMIN)
PARTNER_MANAGER_HEADERS = build_user_headers(PARTNER_MANAGER_ID, UserRole.PARTNER_MANAGER)


def make_admin_headers():
    """Headers for the opaque `PlatformAdmin` principal."""
    return build_user_headers(PLATFORM_ADMIN_ID, UserRole.PLATFORM_ADMIN)


def make_partner_manager_headers():
    """Headers for the opaque `PartnerManager` principal."""
    return build_user_headers(PARTNER_MANAGER_ID, UserRole.PARTNER_MANAGER)


def make_merchant_headers(merchant_id):
    """Headers for a `Merchant`; `X-User-ID` is the merchant row's own id."""
    return build_user_headers(merchant_id, UserRole.MERCHANT)


def make_employer_admin_headers(employer_id):
    """Headers for an `EmployerAdmin`; `X-User-ID` is the employer row's id."""
    return build_user_headers(employer_id, UserRole.EMPLOYER_ADMIN)


def make_employee_headers(membership_id):
    """Headers for an `Employee`; `X-User-ID` is the membership row's id."""
    return build_user_headers(membership_id, UserRole.EMPLOYEE)


def headers_for_role(role, user_id):
    """Headers for an arbitrary role/id pair, for RBAC negative tests."""
    return build_user_headers(user_id, role)


def headers_without_identity(role):
    """Headers that declare a role but carry an empty `X-User-ID`."""
    headers = build_user_headers("", role)
    headers["X-User-ID"] = ""
    return headers
