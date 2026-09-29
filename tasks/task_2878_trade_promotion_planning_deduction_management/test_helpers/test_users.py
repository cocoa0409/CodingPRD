"""
Auth headers for every role of the Trade Promotion Deductions API.

The five internal roles carry an opaque identity: their `X-User-ID` is an
operator identifier that is never compared to any entity's `id`, so the shared
constants below are safe to reuse. Two distinct operator ids exist per internal
role because several rules — segregation of duties on deduction validation and
on dispute write-off — turn on two different operators of the same role.

`CustomerPortalUser` is entity-backed: its `X-User-ID` must be the `id` of the
acting `Customer`, so callers must always mint portal headers through
`make_portal_user_headers(customer_id)` rather than reusing a constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ─── Opaque operator identifiers ──────────────────────

DIRECTOR_USER_ID = "dir-1"
DIRECTOR_ALT_USER_ID = "dir-2"
KAM_USER_ID = "kam-1"
KAM_ALT_USER_ID = "kam-2"
ANALYST_USER_ID = "fin-1"
ANALYST_ALT_USER_ID = "fin-2"
SPECIALIST_USER_ID = "ded-1"
SPECIALIST_ALT_USER_ID = "ded-2"
AUDITOR_USER_ID = "aud-1"
AUDITOR_ALT_USER_ID = "aud-2"

UNKNOWN_ROLE_NAME = "TradeSupervisor"


# ─── Header builders ──────────────────────────────────

def make_director_headers(user_id: str = DIRECTOR_USER_ID) -> Dict[str, str]:
    """Headers for a `TradeMarketingDirector` operator."""
    return build_user_headers(user_id, UserRole.TRADE_MARKETING_DIRECTOR.value)


def make_key_account_manager_headers(user_id: str = KAM_USER_ID) -> Dict[str, str]:
    """Headers for a `KeyAccountManager` operator."""
    return build_user_headers(user_id, UserRole.KEY_ACCOUNT_MANAGER.value)


def make_finance_analyst_headers(user_id: str = ANALYST_USER_ID) -> Dict[str, str]:
    """Headers for a `TradeFinanceAnalyst` operator."""
    return build_user_headers(user_id, UserRole.TRADE_FINANCE_ANALYST.value)


def make_deduction_specialist_headers(user_id: str = SPECIALIST_USER_ID) -> Dict[str, str]:
    """Headers for a `DeductionSpecialist` operator."""
    return build_user_headers(user_id, UserRole.DEDUCTION_SPECIALIST.value)


def make_compliance_auditor_headers(user_id: str = AUDITOR_USER_ID) -> Dict[str, str]:
    """Headers for a `ComplianceAuditor` operator."""
    return build_user_headers(user_id, UserRole.COMPLIANCE_AUDITOR.value)


def make_portal_user_headers(customer_id: str) -> Dict[str, str]:
    """
    Headers for a `CustomerPortalUser`.

    The identifier must be the `id` of the `Customer` the portal login acts as,
    because ownership checks compare a resource's customer foreign key to
    `X-User-ID`.
    """
    return build_user_headers(customer_id, UserRole.CUSTOMER_PORTAL_USER.value)


def make_headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role name — used by role-matrix families."""
    return build_user_headers(user_id, role)


def make_unknown_role_headers(user_id: str = DIRECTOR_USER_ID) -> Dict[str, str]:
    """Headers whose role name is not one of the six declared roles."""
    return build_user_headers(user_id, UNKNOWN_ROLE_NAME)


def make_headers_missing_user_id(role: str = UserRole.TRADE_MARKETING_DIRECTOR.value) -> Dict[str, str]:
    """Headers carrying a role but no `X-User-ID` at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_missing_role(user_id: str = DIRECTOR_USER_ID) -> Dict[str, str]:
    """Headers carrying a user id but no `X-User-Role` at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_blank_user_id(role: str = UserRole.TRADE_MARKETING_DIRECTOR.value) -> Dict[str, str]:
    """
    Headers whose `X-User-ID` is present but empty.

    The value is the empty string, never a whitespace string, which the HTTP
    client would refuse to put on the wire.
    """
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def make_headers_blank_role(user_id: str = DIRECTOR_USER_ID) -> Dict[str, str]:
    """Headers whose `X-User-Role` is present but empty."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


# ─── Shared header constants for the opaque roles ──────

TEST_USERS: Dict[str, Dict[str, str]] = {
    "director": make_director_headers(),
    "director_alt": make_director_headers(DIRECTOR_ALT_USER_ID),
    "key_account_manager": make_key_account_manager_headers(),
    "key_account_manager_alt": make_key_account_manager_headers(KAM_ALT_USER_ID),
    "finance_analyst": make_finance_analyst_headers(),
    "finance_analyst_alt": make_finance_analyst_headers(ANALYST_ALT_USER_ID),
    "deduction_specialist": make_deduction_specialist_headers(),
    "deduction_specialist_alt": make_deduction_specialist_headers(SPECIALIST_ALT_USER_ID),
    "compliance_auditor": make_compliance_auditor_headers(),
    "compliance_auditor_alt": make_compliance_auditor_headers(AUDITOR_ALT_USER_ID),
}

DIRECTOR_HEADERS = TEST_USERS["director"]
DIRECTOR_ALT_HEADERS = TEST_USERS["director_alt"]
KAM_HEADERS = TEST_USERS["key_account_manager"]
KAM_ALT_HEADERS = TEST_USERS["key_account_manager_alt"]
ANALYST_HEADERS = TEST_USERS["finance_analyst"]
ANALYST_ALT_HEADERS = TEST_USERS["finance_analyst_alt"]
SPECIALIST_HEADERS = TEST_USERS["deduction_specialist"]
SPECIALIST_ALT_HEADERS = TEST_USERS["deduction_specialist_alt"]
AUDITOR_HEADERS = TEST_USERS["compliance_auditor"]
AUDITOR_ALT_HEADERS = TEST_USERS["compliance_auditor_alt"]

# The write surface each internal role owns, keyed by role name — the input to
# role-matrix families that exercise a role against another role's endpoints.
ROLE_HEADER_BUILDERS = {
    UserRole.TRADE_MARKETING_DIRECTOR.value: make_director_headers,
    UserRole.KEY_ACCOUNT_MANAGER.value: make_key_account_manager_headers,
    UserRole.TRADE_FINANCE_ANALYST.value: make_finance_analyst_headers,
    UserRole.DEDUCTION_SPECIALIST.value: make_deduction_specialist_headers,
    UserRole.COMPLIANCE_AUDITOR.value: make_compliance_auditor_headers,
}
