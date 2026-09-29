"""Pre-built request headers for every role of the payroll estate (PRD 2.1).

Five of the six roles carry an opaque identity, so a shared constant header dict
is correct for them. `ProviderUser` is the exception: its `X-User-ID` is the `id`
of the acting provider entity, so its headers must be built per provider with
`make_provider_user_headers(provider_id)`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_GLOBAL_PAYROLL_OPS,
    ROLE_PAYROLL_CONTROLLER,
    ROLE_PLATFORM_ADMIN,
    ROLE_PROVIDER_USER,
    ROLE_TREASURY_OFFICER,
)

# ─── Opaque operator identities (PRD 2.1) ─────────────────────────────────────

ADMIN_USER_ID = "admin-01"
OPS_USER_ID = "ops-01"
OPS_2_USER_ID = "ops-02"
CONTROLLER_USER_ID = "ctrl-01"
CONTROLLER_2_USER_ID = "ctrl-02"
TREASURY_APPROVER_USER_ID = "treas-01"
TREASURY_RELEASER_USER_ID = "treas-02"
AUDITOR_USER_ID = "audit-01"

PLATFORM_ADMIN_HEADERS = build_user_headers(ADMIN_USER_ID, ROLE_PLATFORM_ADMIN)
OPS_HEADERS = build_user_headers(OPS_USER_ID, ROLE_GLOBAL_PAYROLL_OPS)
OPS_2_HEADERS = build_user_headers(OPS_2_USER_ID, ROLE_GLOBAL_PAYROLL_OPS)
CONTROLLER_HEADERS = build_user_headers(CONTROLLER_USER_ID, ROLE_PAYROLL_CONTROLLER)
CONTROLLER_2_HEADERS = build_user_headers(CONTROLLER_2_USER_ID, ROLE_PAYROLL_CONTROLLER)
TREASURY_APPROVER_HEADERS = build_user_headers(
    TREASURY_APPROVER_USER_ID, ROLE_TREASURY_OFFICER
)
TREASURY_RELEASER_HEADERS = build_user_headers(
    TREASURY_RELEASER_USER_ID, ROLE_TREASURY_OFFICER
)
AUDITOR_HEADERS = build_user_headers(AUDITOR_USER_ID, ROLE_COMPLIANCE_AUDITOR)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin_headers": PLATFORM_ADMIN_HEADERS,
    "ops_headers": OPS_HEADERS,
    "ops_2_headers": OPS_2_HEADERS,
    "controller_headers": CONTROLLER_HEADERS,
    "controller_2_headers": CONTROLLER_2_HEADERS,
    "treasury_approver_headers": TREASURY_APPROVER_HEADERS,
    "treasury_releaser_headers": TREASURY_RELEASER_HEADERS,
    "auditor_headers": AUDITOR_HEADERS,
}


def make_provider_user_headers(provider_id: str) -> Dict[str, str]:
    """Headers for the in-country provider itself.

    PRD 2.1: when `X-User-Role` is `ProviderUser`, `X-User-ID` is the `id` of the
    acting provider entity, so these headers are always per-instance.
    """
    return build_user_headers(provider_id, ROLE_PROVIDER_USER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identity/role pair, for tests that vary one of the two."""
    return build_user_headers(user_id, role)


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """Headers whose `X-User-ID` is the literal empty string, not whitespace."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers with the `X-User-ID` header omitted entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers with the `X-User-Role` header omitted entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
