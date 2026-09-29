"""Pre-built role headers for every role the PRD declares.

Both headers are always sent as non-empty strings; the deliberately blank
variants below use the empty string "" rather than whitespace, because a
whitespace-only header value is rejected by the HTTP layer before the request
is ever sent.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# --------------------------------------------------------------------------
# Shared constants.  Safe for every role whose authorisation does not depend
# on the caller owning the subject row.  DonationPartner is the one role whose
# X-User-ID must equal a real FoodBankPartner id, so its shared constant is
# only usable where no ownership check runs.
# --------------------------------------------------------------------------

ADMIN_USER_ID = "u-admin-1"
MANAGER_USER_ID = "u-mgr-1"
MANAGER_2_USER_ID = "u-mgr-2"
CLERK_USER_ID = "u-clerk-1"
CLERK_2_USER_ID = "u-clerk-2"
AUDITOR_USER_ID = "u-auditor-1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, "StoreOperationsAdmin"),
    "manager_headers": build_user_headers(MANAGER_USER_ID, "DepartmentManager"),
    "manager_2_headers": build_user_headers(MANAGER_2_USER_ID, "DepartmentManager"),
    "clerk_headers": build_user_headers(CLERK_USER_ID, "FreshClerk"),
    "clerk_2_headers": build_user_headers(CLERK_2_USER_ID, "FreshClerk"),
    "auditor_headers": build_user_headers(AUDITOR_USER_ID, "ComplianceAuditor"),
    # Fallback only: never use for an ownership-gated pickup call.
    "partner_headers": build_user_headers("u-partner-1", "DonationPartner"),
}


# --------------------------------------------------------------------------
# Per-instance builders.
# --------------------------------------------------------------------------


def make_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "StoreOperationsAdmin")


def make_manager_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "DepartmentManager")


def make_clerk_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "FreshClerk")


def make_auditor_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "ComplianceAuditor")


def make_partner_headers(partner_id: str) -> Dict[str, str]:
    """For DonationPartner.

    The PRD makes the X-User-ID of a DonationPartner the id of its own
    FoodBankPartner row, so every ownership-gated pickup call must pass the
    real partner id here.
    """
    return build_user_headers(partner_id, "DonationPartner")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary user_id/role pair, including roles outside the declared set."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Both headers present, X-User-ID an empty string."""
    return build_user_headers("", role)


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Both headers present, X-User-Role an empty string."""
    return build_user_headers(user_id, "")


def headers_missing_both() -> Dict[str, str]:
    """Neither auth header present at all."""
    return {"Content-Type": "application/json"}


def headers_missing_user_id(role: str) -> Dict[str, str]:
    """X-User-ID header absent entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str) -> Dict[str, str]:
    """X-User-Role header absent entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


# --------------------------------------------------------------------------
# Shared-role accessors.  Each call returns a fresh dict so a caller that adds
# or drops a header cannot corrupt the shared table.
# --------------------------------------------------------------------------


def admin_headers() -> Dict[str, str]:
    return dict(TEST_USERS["admin_headers"])


def manager_headers() -> Dict[str, str]:
    return dict(TEST_USERS["manager_headers"])


def manager_2_headers() -> Dict[str, str]:
    return dict(TEST_USERS["manager_2_headers"])


def clerk_headers() -> Dict[str, str]:
    return dict(TEST_USERS["clerk_headers"])


def clerk_2_headers() -> Dict[str, str]:
    return dict(TEST_USERS["clerk_2_headers"])


def auditor_headers() -> Dict[str, str]:
    return dict(TEST_USERS["auditor_headers"])
