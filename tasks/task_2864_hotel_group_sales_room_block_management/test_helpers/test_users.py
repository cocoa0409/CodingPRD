"""Pre-built request headers for the seven roles of PRD 2.1.

Six roles carry an opaque ``X-User-ID``; distinct operators inside one role
get distinct identifiers so that the separation-of-duties gate of PRD 2.1
("the acting X-User-ID must differ from requested_by_user_id ... from
prepared_by_user_id") can be exercised without ambiguity.

``GroupContact`` is the one entity-backed role: its ``X-User-ID`` is the id
of the acting ``GroupAccount``, so its headers are built per account.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque operator identifiers (PRD 2.1: "an opaque operator identifier that
# is not tied to any persisted entity").
SALES_MANAGER_ID = "sm-001"
SALES_MANAGER_ALT_ID = "sm-007"
REVENUE_MANAGER_ID = "rm-001"
REVENUE_MANAGER_ALT_ID = "rm-002"
REVENUE_MANAGER_THIRD_ID = "rm-003"
CONTRACT_ADMIN_ID = "ca-001"
CONTRACT_ADMIN_ALT_ID = "ca-002"
RESERVATIONS_AGENT_ID = "ra-001"
RESERVATIONS_AGENT_ALT_ID = "ra-002"
ACCOUNTING_CLERK_ID = "ac-001"
ACCOUNTING_CLERK_ALT_ID = "ac-002"
SYSTEM_OPERATOR_ID = "op-001"
UNDECLARED_ROLE_ID = "gm-001"


def make_sales_manager_headers(user_id: str = SALES_MANAGER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.SALES_MANAGER)


def make_revenue_manager_headers(user_id: str = REVENUE_MANAGER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.REVENUE_MANAGER)


def make_contract_admin_headers(user_id: str = CONTRACT_ADMIN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.CONTRACT_ADMIN)


def make_reservations_agent_headers(
    user_id: str = RESERVATIONS_AGENT_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.RESERVATIONS_AGENT)


def make_accounting_clerk_headers(user_id: str = ACCOUNTING_CLERK_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.ACCOUNTING_CLERK)


def make_system_operator_headers(user_id: str = SYSTEM_OPERATOR_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.SYSTEM_OPERATOR)


def make_group_contact_headers(account_id: str) -> Dict[str, str]:
    """Headers for the entity-backed GroupContact role.

    PRD 2.1: "When X-User-Role is GroupContact, X-User-ID is the id of the
    acting client organization - a GroupAccount row."
    """
    return build_user_headers(account_id, Role.GROUP_CONTACT)


def make_undeclared_role_headers(
    user_id: str = UNDECLARED_ROLE_ID,
) -> Dict[str, str]:
    """Headers naming a role outside the seven declared ones (PRD 2.1)."""
    return build_user_headers(user_id, "GeneralManager")


NO_AUTH_HEADERS: Dict[str, str] = {}

# Convenience singletons for the common actors.
SALES_MANAGER = make_sales_manager_headers()
SALES_MANAGER_ALT = make_sales_manager_headers(SALES_MANAGER_ALT_ID)
REVENUE_MANAGER = make_revenue_manager_headers()
REVENUE_MANAGER_ALT = make_revenue_manager_headers(REVENUE_MANAGER_ALT_ID)
REVENUE_MANAGER_THIRD = make_revenue_manager_headers(REVENUE_MANAGER_THIRD_ID)
CONTRACT_ADMIN = make_contract_admin_headers()
CONTRACT_ADMIN_ALT = make_contract_admin_headers(CONTRACT_ADMIN_ALT_ID)
RESERVATIONS_AGENT = make_reservations_agent_headers()
RESERVATIONS_AGENT_ALT = make_reservations_agent_headers(RESERVATIONS_AGENT_ALT_ID)
ACCOUNTING_CLERK = make_accounting_clerk_headers()
ACCOUNTING_CLERK_ALT = make_accounting_clerk_headers(ACCOUNTING_CLERK_ALT_ID)
SYSTEM_OPERATOR = make_system_operator_headers()
UNDECLARED_ROLE_HEADERS = make_undeclared_role_headers()
