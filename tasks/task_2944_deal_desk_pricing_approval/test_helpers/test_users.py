"""Role headers. Identity is opaque for every role: `X-User-ID` is an operator
identifier that is recorded but never resolved against a stored record, so
distinct callers are modelled purely by distinct identifier strings.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Distinct opaque operator identifiers. Ownership, segregation of duties and
# delegation all compare these strings, so each distinct actor needs its own.
USER_IDS = {
    "admin": "u-admin-1",
    "rep": "u-rep-1",
    "other_rep": "u-rep-2",
    "analyst": "u-desk-1",
    "director": "u-dir-1",
    "other_director": "u-dir-2",
    "vp": "u-vp-1",
    "cfo": "u-cfo-1",
    "legal": "u-legal-1",
    "accountant": "u-rev-1",
    # Operators that act under two different roles across one scenario.
    "dual_one": "u-dual-1",
    "dual_two": "u-dual-2",
    # Delegation grantees.
    "grantee_a": "u-appr-a",
    "grantee_b": "u-appr-b",
}


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary (opaque identifier, role) pair."""
    return build_user_headers(user_id, role)


def make_platform_admin_headers(user_id: str = USER_IDS["admin"]) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_sales_rep_headers(user_id: str = USER_IDS["rep"]) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.SALES_REP.value)


def make_deal_desk_analyst_headers(user_id: str = USER_IDS["analyst"]) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.DEAL_DESK_ANALYST.value)


def make_sales_director_headers(user_id: str = USER_IDS["director"]) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.SALES_DIRECTOR.value)


def make_vp_sales_headers(user_id: str = USER_IDS["vp"]) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.VP_SALES.value)


def make_cfo_headers(user_id: str = USER_IDS["cfo"]) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.CFO.value)


def make_legal_counsel_headers(user_id: str = USER_IDS["legal"]) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.LEGAL_COUNSEL.value)


def make_revenue_accountant_headers(user_id: str = USER_IDS["accountant"]) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.REVENUE_ACCOUNTANT.value)


TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin_headers": make_platform_admin_headers(),
    "rep_headers": make_sales_rep_headers(),
    "other_rep_headers": make_sales_rep_headers(USER_IDS["other_rep"]),
    "analyst_headers": make_deal_desk_analyst_headers(),
    "director_headers": make_sales_director_headers(),
    "other_director_headers": make_sales_director_headers(USER_IDS["other_director"]),
    "vp_headers": make_vp_sales_headers(),
    "cfo_headers": make_cfo_headers(),
    "legal_headers": make_legal_counsel_headers(),
    "accountant_headers": make_revenue_accountant_headers(),
}


def headers_missing_user_id(role: str) -> Dict[str, str]:
    """Headers with `X-User-ID` absent altogether."""
    headers = build_user_headers("unused", role)
    headers.pop("X-User-ID", None)
    return headers


def headers_missing_role(user_id: str) -> Dict[str, str]:
    """Headers with `X-User-Role` absent altogether."""
    headers = build_user_headers(user_id, "unused")
    headers.pop("X-User-Role", None)
    return headers


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """Headers whose `X-User-ID` is present but the empty string."""
    headers = build_user_headers("unused", role)
    headers["X-User-ID"] = ""
    return headers


def headers_with_empty_role(user_id: str) -> Dict[str, str]:
    """Headers whose `X-User-Role` is present but the empty string."""
    headers = build_user_headers(user_id, "unused")
    headers["X-User-Role"] = ""
    return headers
