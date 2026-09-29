"""Pre-built role headers for every role in PRD §2.1.

Five of the six roles are opaque operators: their ``X-User-ID`` is any stable
operator identifier and no row has to exist for it. ``Customer`` is the one
identity-bearing role — a Customer caller's ``X-User-ID`` must be the
``Customer.id`` of the row they own, so ownership-gated calls always go through
``make_customer_headers(customer["id"])``.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Stable operator identifiers. Two authenticators and two technicians exist so
# that segregation-of-duties scenarios always have a distinct second signer.
PROGRAM_ADMIN_ID = "admin-001"
INTAKE_AGENT_ID = "intake-001"
AUTHENTICATOR_ID = "auth-001"
SECOND_AUTHENTICATOR_ID = "auth-002"
REFURB_TECHNICIAN_ID = "tech-001"
SECOND_REFURB_TECHNICIAN_ID = "tech-002"
MERCHANDISING_MANAGER_ID = "merch-001"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin_headers": build_user_headers(PROGRAM_ADMIN_ID, UserRole.PROGRAM_ADMIN.value),
    "intake_agent_headers": build_user_headers(
        INTAKE_AGENT_ID, UserRole.INTAKE_AGENT.value
    ),
    "authenticator_headers": build_user_headers(
        AUTHENTICATOR_ID, UserRole.AUTHENTICATOR.value
    ),
    "second_authenticator_headers": build_user_headers(
        SECOND_AUTHENTICATOR_ID, UserRole.AUTHENTICATOR.value
    ),
    "refurb_technician_headers": build_user_headers(
        REFURB_TECHNICIAN_ID, UserRole.REFURB_TECHNICIAN.value
    ),
    "second_refurb_technician_headers": build_user_headers(
        SECOND_REFURB_TECHNICIAN_ID, UserRole.REFURB_TECHNICIAN.value
    ),
    "merchandising_manager_headers": build_user_headers(
        MERCHANDISING_MANAGER_ID, UserRole.MERCHANDISING_MANAGER.value
    ),
    # Fallback only for Customer-role tests that never touch a row's ownership.
    "customer_headers": build_user_headers("customer-unbound", UserRole.CUSTOMER.value),
}

ADMIN = TEST_USERS["admin_headers"]
INTAKE = TEST_USERS["intake_agent_headers"]
AUTH1 = TEST_USERS["authenticator_headers"]
AUTH2 = TEST_USERS["second_authenticator_headers"]
TECH1 = TEST_USERS["refurb_technician_headers"]
TECH2 = TEST_USERS["second_refurb_technician_headers"]
MERCH = TEST_USERS["merchandising_manager_headers"]


def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """Headers for the Customer role, whose identity is a Customer row.

    Always pass the real ``Customer.id``: ownership gates compare the header
    against the row and refuse anything else with ERR_NOT_RESOURCE_OWNER.
    """
    return build_user_headers(customer_id, UserRole.CUSTOMER.value)


def make_admin_headers(user_id: str = PROGRAM_ADMIN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.PROGRAM_ADMIN.value)


def make_intake_agent_headers(user_id: str = INTAKE_AGENT_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.INTAKE_AGENT.value)


def make_authenticator_headers(user_id: str = AUTHENTICATOR_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.AUTHENTICATOR.value)


def make_refurb_technician_headers(
    user_id: str = REFURB_TECHNICIAN_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.REFURB_TECHNICIAN.value)


def make_merchandising_manager_headers(
    user_id: str = MERCHANDISING_MANAGER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.MERCHANDISING_MANAGER.value)


def headers_without_user_id(role: str = UserRole.PROGRAM_ADMIN.value) -> Dict[str, str]:
    """A request that declares a role but sends an empty ``X-User-ID``."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_whitespace_user_id(
    role: str = UserRole.PROGRAM_ADMIN.value,
) -> Dict[str, str]:
    """A request whose ``X-User-ID`` is made up only of whitespace."""
    return {"X-User-ID": "   ", "X-User-Role": role, "Content-Type": "application/json"}
