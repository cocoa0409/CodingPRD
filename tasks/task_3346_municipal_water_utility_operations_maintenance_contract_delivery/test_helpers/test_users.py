"""Pre-built role headers for every role in the PRD (PRD §2.1, §2.9)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants -- safe for opaque roles, and for tests whose success does not
# depend on the caller owning the subject resource.
TEST_USERS = {
    # opaque role: the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    # entity_backed:Municipality -- fallback for non-ownership-gated calls only.
    "municipality_admin_headers": build_user_headers("test-municipality-admin-1", "MunicipalityAdmin"),
    # entity_backed:Contract -- fallback for non-ownership-gated calls only.
    "operator_admin_headers": build_user_headers("test-operator-admin-1", "OperatorAdmin"),
    # entity_backed:Employee -- fallback for non-ownership-gated calls only.
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
}


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    """PlatformAdmin is opaque; the id is recorded but never compared."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_municipality_admin_headers(user_id: str) -> dict:
    """For MunicipalityAdmin (entity_backed:Municipality). Pass the actual
    Municipality.id as user_id on every ownership-gated call."""
    return build_user_headers(user_id, "MunicipalityAdmin")


def make_operator_admin_headers(user_id: str) -> dict:
    """For OperatorAdmin (entity_backed:Contract). Pass the actual Contract.id
    as user_id on every ownership-gated call."""
    return build_user_headers(user_id, "OperatorAdmin")


def make_employee_headers(user_id: str) -> dict:
    """For Employee (entity_backed:Employee). Self-service calls must carry the
    employee's own id."""
    return build_user_headers(user_id, "Employee")


def missing_auth_headers() -> dict:
    """Neither X-User-ID nor X-User-Role: rejects with ERR_UNAUTHENTICATED."""
    return {"Content-Type": "application/json"}


def unknown_role_headers(user_id: str = "someone-1") -> dict:
    """A role name that is not one of the four declared roles."""
    return build_user_headers(user_id, "Supervisor")