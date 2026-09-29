"""Pre-built role headers for the five roles the PRD recognises.

PRD §2.1: when the role is ``DepartmentManager`` the ``X-User-ID`` header is the
``id`` of the acting ``BakeryDepartment``, so any ownership-gated manager call
must be built with :func:`make_department_manager_headers` and the real
department id.  The other four roles carry opaque operator identifiers that the
server never compares to an entity id, so a shared constant is the canonical
form for them.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers (PRD §2.1).
REGIONAL_ADMIN_USER_ID = "regional-admin-01"
BAKER_ONE_USER_ID = "baker-01"
BAKER_TWO_USER_ID = "baker-02"
DECORATOR_USER_ID = "decorator-01"
CAKE_DESK_USER_ID = "cake-desk-01"

# Placeholder manager identity: only safe for calls that fail before the
# department-scope check (missing header, unknown role, 400 payloads).
PLACEHOLDER_DEPARTMENT_ID = "department-manager-unbound"


TEST_USERS = {
    "regional_admin_headers": build_user_headers(
        REGIONAL_ADMIN_USER_ID, "RegionalAdmin"
    ),
    "baker_headers": build_user_headers(BAKER_ONE_USER_ID, "Baker"),
    "second_baker_headers": build_user_headers(BAKER_TWO_USER_ID, "Baker"),
    "decorator_headers": build_user_headers(DECORATOR_USER_ID, "Decorator"),
    "cake_desk_headers": build_user_headers(CAKE_DESK_USER_ID, "CakeDesk"),
    # Fallback only — never use for an ownership-gated manager call.
    "department_manager_headers": build_user_headers(
        PLACEHOLDER_DEPARTMENT_ID, "DepartmentManager"
    ),
}


def make_department_manager_headers(department_id: str) -> dict:
    """Headers for a ``DepartmentManager`` acting for ``department_id``.

    PRD §2.1 resolves the manager's ``X-User-ID`` to the acting department's
    ``id``, so this must be called with the created department's id whenever the
    request touches that department's data.
    """
    return build_user_headers(department_id, "DepartmentManager")


def make_regional_admin_headers(user_id: str = REGIONAL_ADMIN_USER_ID) -> dict:
    """Headers for a ``RegionalAdmin`` (opaque identity)."""
    return build_user_headers(user_id, "RegionalAdmin")


def make_baker_headers(user_id: str = BAKER_ONE_USER_ID) -> dict:
    """Headers for a ``Baker`` (opaque identity)."""
    return build_user_headers(user_id, "Baker")


def make_decorator_headers(user_id: str = DECORATOR_USER_ID) -> dict:
    """Headers for a ``Decorator`` (opaque identity)."""
    return build_user_headers(user_id, "Decorator")


def make_cake_desk_headers(user_id: str = CAKE_DESK_USER_ID) -> dict:
    """Headers for a ``CakeDesk`` operator (opaque identity)."""
    return build_user_headers(user_id, "CakeDesk")


def headers_without_user_id(role: str = "DepartmentManager") -> dict:
    """Headers carrying only ``X-User-Role`` — used for the 401 path."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
