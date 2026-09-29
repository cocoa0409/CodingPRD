"""Identity headers.

The PRD requires ``X-User-ID`` and ``X-User-Role`` on every endpoint except the
clock setter.

* ``ProgramAdmin`` and ``EmergencyCoordinator`` identifiers are opaque -- they
  are only recorded on the rows they create, so fixed constants are safe.
* ``Engineer`` identifiers must be the id of an Engineer row and ``DamOwner``
  identifiers must be the id of an Owner row, so those headers must be built
  per entity with the builders below.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_DAM_OWNER,
    ROLE_EMERGENCY_COORDINATOR,
    ROLE_ENGINEER,
    ROLE_PROGRAM_ADMIN,
)

# Opaque-identity roles: any stable uuid works, the API only records it.
TEST_USERS: dict[str, dict[str, str]] = {
    "program_admin": {
        "user_id": "11111111-1111-4111-8111-111111111111",
        "role": ROLE_PROGRAM_ADMIN,
    },
    "program_admin_alt": {
        "user_id": "11111111-1111-4111-8111-111111111112",
        "role": ROLE_PROGRAM_ADMIN,
    },
    "emergency_coordinator": {
        "user_id": "22222222-2222-4222-8222-222222222222",
        "role": ROLE_EMERGENCY_COORDINATOR,
    },
    "emergency_coordinator_alt": {
        "user_id": "22222222-2222-4222-8222-222222222223",
        "role": ROLE_EMERGENCY_COORDINATOR,
    },
}


def _headers(user_id: str, role: str) -> dict[str, str]:
    return build_user_headers(user_id, role)


def admin_headers() -> dict[str, str]:
    """Headers for the ProgramAdmin actor."""
    return _headers(
        TEST_USERS["program_admin"]["user_id"], TEST_USERS["program_admin"]["role"]
    )


def admin_alt_headers() -> dict[str, str]:
    """Headers for a second, distinct ProgramAdmin actor."""
    return _headers(
        TEST_USERS["program_admin_alt"]["user_id"],
        TEST_USERS["program_admin_alt"]["role"],
    )


def coordinator_headers() -> dict[str, str]:
    """Headers for the EmergencyCoordinator actor."""
    return _headers(
        TEST_USERS["emergency_coordinator"]["user_id"],
        TEST_USERS["emergency_coordinator"]["role"],
    )


def coordinator_alt_headers() -> dict[str, str]:
    """Headers for a second, distinct EmergencyCoordinator actor."""
    return _headers(
        TEST_USERS["emergency_coordinator_alt"]["user_id"],
        TEST_USERS["emergency_coordinator_alt"]["role"],
    )


def make_engineer_headers(engineer_id: str) -> dict[str, str]:
    """Headers whose ``X-User-ID`` is the Engineer row id, as the PRD requires."""
    return _headers(engineer_id, ROLE_ENGINEER)


def make_owner_headers(owner_id: str) -> dict[str, str]:
    """Headers whose ``X-User-ID`` is the Owner row id, as the PRD requires."""
    return _headers(owner_id, ROLE_DAM_OWNER)


def make_headers(user_id: str, role: str) -> dict[str, str]:
    """Arbitrary identity/role pair, for authorisation-boundary tests."""
    return _headers(user_id, role)


def headers_without_user_id(role: str) -> dict[str, str]:
    """Headers carrying only the role -- used to exercise the auth rung."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> dict[str, str]:
    """Headers carrying only the identity -- used to exercise the auth rung."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


NO_HEADERS: dict[str, str] = {"Content-Type": "application/json"}
