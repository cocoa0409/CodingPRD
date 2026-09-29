"""Pre-built role headers for the eight roles of the PRD.

Per PRD §2.1, `AccountAdmin` is entity-backed: its `X-User-ID` is the `id` of the
acting `Account`, and ownership checks compare a resource's account-bearing field
against it. Any ownership-sensitive call therefore MUST use
`make_account_admin_headers(account_id)` with the real account id; the shared
`TEST_USERS["account_admin_headers"]` constant is only safe where the outcome
does not depend on ownership (for example a role-not-permitted assertion).

The other seven roles carry opaque operator identifiers. Two of them are
recorded and later compared by the segregation-of-duties rules of PRD §2.10,
so distinct user ids are provided for them:
  - `porting-1` files port requests, `liaison-1` / `liaison-2` transcribe them;
  - `billing-1` assesses fees, `billing-2` voids them.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ACCOUNT_ADMIN,
    ROLE_BILLING_ADMIN,
    ROLE_CARRIER_LIAISON,
    ROLE_E911_VALIDATOR,
    ROLE_NUMBERING_ADMIN,
    ROLE_PLATFORM_ADMIN,
    ROLE_PORTING_SPECIALIST,
    ROLE_SECURITY_ANALYST,
)

PLATFORM_USER_ID = "platform-1"
NUMBERING_USER_ID = "numbering-1"
PORTING_USER_ID = "porting-1"
PORTING_USER_ID_ALT = "porting-2"
LIAISON_USER_ID = "liaison-1"
LIAISON_USER_ID_ALT = "liaison-2"
VALIDATOR_USER_ID = "validator-1"
ANALYST_USER_ID = "analyst-1"
BILLING_USER_ID = "billing-1"
BILLING_USER_ID_ALT = "billing-2"

TEST_USERS = {
    "platform_admin_headers": build_user_headers(PLATFORM_USER_ID, ROLE_PLATFORM_ADMIN),
    "numbering_admin_headers": build_user_headers(NUMBERING_USER_ID, ROLE_NUMBERING_ADMIN),
    "porting_specialist_headers": build_user_headers(PORTING_USER_ID, ROLE_PORTING_SPECIALIST),
    "carrier_liaison_headers": build_user_headers(LIAISON_USER_ID, ROLE_CARRIER_LIAISON),
    "e911_validator_headers": build_user_headers(VALIDATOR_USER_ID, ROLE_E911_VALIDATOR),
    "security_analyst_headers": build_user_headers(ANALYST_USER_ID, ROLE_SECURITY_ANALYST),
    "billing_admin_headers": build_user_headers(BILLING_USER_ID, ROLE_BILLING_ADMIN),
    # Entity-backed role: placeholder id, non-ownership assertions only.
    "account_admin_headers": build_user_headers("account-placeholder", ROLE_ACCOUNT_ADMIN),
}


def make_platform_admin_headers(user_id: str = PLATFORM_USER_ID) -> dict:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_numbering_admin_headers(user_id: str = NUMBERING_USER_ID) -> dict:
    return build_user_headers(user_id, ROLE_NUMBERING_ADMIN)


def make_porting_specialist_headers(user_id: str = PORTING_USER_ID) -> dict:
    return build_user_headers(user_id, ROLE_PORTING_SPECIALIST)


def make_carrier_liaison_headers(user_id: str = LIAISON_USER_ID) -> dict:
    """The liaison must differ from a port request's created_by_user_id
    (PRD §2.10), so the acting id is always explicit."""
    return build_user_headers(user_id, ROLE_CARRIER_LIAISON)


def make_e911_validator_headers(user_id: str = VALIDATOR_USER_ID) -> dict:
    return build_user_headers(user_id, ROLE_E911_VALIDATOR)


def make_security_analyst_headers(user_id: str = ANALYST_USER_ID) -> dict:
    return build_user_headers(user_id, ROLE_SECURITY_ANALYST)


def make_billing_admin_headers(user_id: str = BILLING_USER_ID) -> dict:
    """The voiding administrator must differ from the assessing one
    (PRD §3.9), so the acting id is always explicit."""
    return build_user_headers(user_id, ROLE_BILLING_ADMIN)


def make_account_admin_headers(account_id: str) -> dict:
    """`AccountAdmin` is entity-backed: pass the owning `Account.id`."""
    return build_user_headers(account_id, ROLE_ACCOUNT_ADMIN)


def make_headers(role: str, user_id: str) -> dict:
    """Escape hatch for role-matrix tests that iterate over role names."""
    return build_user_headers(user_id, role)


def make_blank_role_headers(user_id: str = PLATFORM_USER_ID) -> dict:
    """Headers whose `X-User-Role` is present but empty (PRD §2.1).

    The value is the empty string, not a space: a whitespace value is a
    different (non-empty) header and would not exercise the rule.
    """
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def make_blank_user_id_headers(role: str = ROLE_PLATFORM_ADMIN) -> dict:
    """Headers whose `X-User-ID` is present but empty (PRD §2.1)."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def make_unknown_role_headers(user_id: str = PLATFORM_USER_ID) -> dict:
    """Headers naming a role that is not one of the eight (PRD §2.1)."""
    return build_user_headers(user_id, "SupremeOverlord")


def make_headers_without_role(user_id: str = PLATFORM_USER_ID) -> dict:
    """Headers with `X-User-Role` absent entirely (PRD §2.1)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_without_user_id(role: str = ROLE_PLATFORM_ADMIN) -> dict:
    """Headers with `X-User-ID` absent entirely (PRD §2.1)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
