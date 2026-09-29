"""Identity headers for the six roles of PRD §2.1.

PRD §2.1 requires both ``X-User-ID`` and ``X-User-Role`` on every request other
than the clock hook, and treats an empty string as an absent header.  Staff
roles carry opaque identifiers; ``CustomerContact`` is the one entity-backed
role, whose ``X-User-ID`` **is** the ``CustomerAccount.id`` it speaks for, so a
customer identity can only be built once the account exists.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from . import constants as C

# Opaque staff identifiers.
PLATFORM_ADMIN_ID = "pa-001"
ACCOUNT_MANAGER_ID = "am-001"
ACCOUNT_MANAGER_2_ID = "am-002"
DISPATCH_COORDINATOR_ID = "dc-001"
DISPATCH_COORDINATOR_2_ID = "dc-002"
MUNICIPAL_LIAISON_ID = "ml-001"
YARD_AUDITOR_ID = "ya-001"
YARD_AUDITOR_2_ID = "ya-002"

PLATFORM_ADMIN = build_user_headers(PLATFORM_ADMIN_ID, C.ROLE_PLATFORM_ADMIN)
ACCOUNT_MANAGER = build_user_headers(ACCOUNT_MANAGER_ID, C.ROLE_ACCOUNT_MANAGER)
ACCOUNT_MANAGER_2 = build_user_headers(ACCOUNT_MANAGER_2_ID, C.ROLE_ACCOUNT_MANAGER)
DISPATCH_COORDINATOR = build_user_headers(
    DISPATCH_COORDINATOR_ID, C.ROLE_DISPATCH_COORDINATOR
)
DISPATCH_COORDINATOR_2 = build_user_headers(
    DISPATCH_COORDINATOR_2_ID, C.ROLE_DISPATCH_COORDINATOR
)
MUNICIPAL_LIAISON = build_user_headers(MUNICIPAL_LIAISON_ID, C.ROLE_MUNICIPAL_LIAISON)
YARD_AUDITOR = build_user_headers(YARD_AUDITOR_ID, C.ROLE_YARD_AUDITOR)
YARD_AUDITOR_2 = build_user_headers(YARD_AUDITOR_2_ID, C.ROLE_YARD_AUDITOR)

#: Every role keyed by its exact PRD spelling, for role-matrix parametrisation.
TEST_USERS: Dict[str, Dict[str, str]] = {
    C.ROLE_PLATFORM_ADMIN: PLATFORM_ADMIN,
    C.ROLE_ACCOUNT_MANAGER: ACCOUNT_MANAGER,
    C.ROLE_DISPATCH_COORDINATOR: DISPATCH_COORDINATOR,
    C.ROLE_MUNICIPAL_LIAISON: MUNICIPAL_LIAISON,
    C.ROLE_YARD_AUDITOR: YARD_AUDITOR,
}


def make_customer_contact_headers(customer_account_id: str) -> Dict[str, str]:
    """Headers for the customer of ``customer_account_id`` (PRD §2.1).

    The ``X-User-ID`` of a ``CustomerContact`` is the account identifier itself,
    so account scope is decided by which account this identity names.
    """
    return build_user_headers(customer_account_id, C.ROLE_CUSTOMER_CONTACT)


def make_platform_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, C.ROLE_PLATFORM_ADMIN)


def make_account_manager_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, C.ROLE_ACCOUNT_MANAGER)


def make_dispatch_coordinator_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, C.ROLE_DISPATCH_COORDINATOR)


def make_municipal_liaison_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, C.ROLE_MUNICIPAL_LIAISON)


def make_yard_auditor_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, C.ROLE_YARD_AUDITOR)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary identifier/role pair, including unknown roles."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers whose ``X-User-ID`` is absent entirely (PRD §2.1)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers whose ``X-User-Role`` is absent entirely (PRD §2.1)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_blank_user_id(role: str) -> Dict[str, str]:
    """Headers whose ``X-User-ID`` is the empty string (PRD §2.1)."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_blank_role(user_id: str) -> Dict[str, str]:
    """Headers whose ``X-User-Role`` is the empty string (PRD §2.1)."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
