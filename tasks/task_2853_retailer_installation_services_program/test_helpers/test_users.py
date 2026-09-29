"""Identity headers.

The PRD splits identity semantics by role. For `ProgramAdmin`, `NetworkManager`,
`ProjectCoordinator` and `ServiceManager` the `X-User-ID` is an opaque operator
identifier that is never compared to any entity id, so a fixed handle per role is
correct and each role gets its own. For `Installer` the `X-User-ID` must be the id
of the acting installer row, and for `Customer` it must be the id of the acting
customer row: those two must therefore be built per entity, which is what
`make_installer_headers` and `make_customer_headers` are for. Two distinct owners
never share a handle.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque operator handles — one per operator role, deliberately distinct so that a
# recorded handle (for example `escalated_to_user_id`) identifies who acted.
PROGRAM_ADMIN_USER_ID = "admin-001"
NETWORK_MANAGER_USER_ID = "netmgr-2001"
PROJECT_COORDINATOR_USER_ID = "coord-001"
SECOND_COORDINATOR_USER_ID = "coord-4001"
SERVICE_MANAGER_USER_ID = "sm-7001"

TEST_USERS: Dict[str, Dict[str, str]] = {
    Role.PROGRAM_ADMIN: {"user_id": PROGRAM_ADMIN_USER_ID, "role": Role.PROGRAM_ADMIN},
    Role.NETWORK_MANAGER: {
        "user_id": NETWORK_MANAGER_USER_ID,
        "role": Role.NETWORK_MANAGER,
    },
    Role.PROJECT_COORDINATOR: {
        "user_id": PROJECT_COORDINATOR_USER_ID,
        "role": Role.PROJECT_COORDINATOR,
    },
    Role.SERVICE_MANAGER: {
        "user_id": SERVICE_MANAGER_USER_ID,
        "role": Role.SERVICE_MANAGER,
    },
}


def headers_for(role: str, user_id: str) -> Dict[str, str]:
    """Build headers for any role with an explicit `X-User-ID`."""
    return build_user_headers(user_id, role)


# ---------------------------------------------------------------------------
# Operator roles: fixed opaque handles
# ---------------------------------------------------------------------------
def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.PROGRAM_ADMIN)


def make_network_manager_headers(
    user_id: str = NETWORK_MANAGER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.NETWORK_MANAGER)


def make_project_coordinator_headers(
    user_id: str = PROJECT_COORDINATOR_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.PROJECT_COORDINATOR)


def make_service_manager_headers(
    user_id: str = SERVICE_MANAGER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.SERVICE_MANAGER)


# ---------------------------------------------------------------------------
# Entity-backed roles: the handle IS the entity id
# ---------------------------------------------------------------------------
def make_installer_headers(installer_id: str) -> Dict[str, str]:
    """`X-User-ID` is the id of the acting Installer row."""
    return build_user_headers(installer_id, Role.INSTALLER)


def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """`X-User-ID` is the id of the acting Customer row."""
    return build_user_headers(customer_id, Role.CUSTOMER)


# Pre-built operator header dicts for convenience.
PROGRAM_ADMIN = make_program_admin_headers()
NETWORK_MANAGER = make_network_manager_headers()
PROJECT_COORDINATOR = make_project_coordinator_headers()
SERVICE_MANAGER = make_service_manager_headers()
