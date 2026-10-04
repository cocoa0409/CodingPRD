"""Pre-built role headers for every role in the PRD (§2.1).

All eight roles have opaque identities: X-User-ID is never compared against
any entity's id. It IS compared operator-to-operator by the
segregation-of-duties rule (PRD §3.7): the accept/reject actor's X-User-ID
must differ from the report's filed_by_user_id. Use the make_*_headers
builders whenever a test needs to control the exact X-User-ID (e.g. a
ComplianceOfficer reusing the filer's id to trip ERR_SEGREGATION_OF_DUTIES).

The shared BondedPreparer and ComplianceOfficer constants below use distinct
X-User-IDs, so the default pair always satisfies segregation of duties.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Shared constants — canonical for all roles (all identities are opaque).
TEST_USERS = {
    "distillery_planner_headers": build_user_headers("test-planner-1", UserRole.DISTILLERY_PLANNER.value),
    "operations_director_headers": build_user_headers("test-ops-director-1", UserRole.OPERATIONS_DIRECTOR.value),
    "warehouse_manager_headers": build_user_headers("test-warehouse-manager-1", UserRole.WAREHOUSE_MANAGER.value),
    "master_blender_headers": build_user_headers("test-master-blender-1", UserRole.MASTER_BLENDER.value),
    "program_director_headers": build_user_headers("test-program-director-1", UserRole.PROGRAM_DIRECTOR.value),
    "bonded_preparer_headers": build_user_headers("test-bonded-preparer-1", UserRole.BONDED_PREPARER.value),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", UserRole.COMPLIANCE_OFFICER.value),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", UserRole.PLATFORM_ADMIN.value),
}

# Distinct default user ids used by the bonded-report workflow fixtures.
DEFAULT_PREPARER_USER_ID = "test-bonded-preparer-1"
DEFAULT_OFFICER_USER_ID = "test-compliance-officer-1"


def make_distillery_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.DISTILLERY_PLANNER.value)


def make_operations_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.OPERATIONS_DIRECTOR.value)


def make_warehouse_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.WAREHOUSE_MANAGER.value)


def make_master_blender_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.MASTER_BLENDER.value)


def make_program_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.PROGRAM_DIRECTOR.value)


def make_bonded_preparer_headers(user_id: str) -> dict:
    """BondedPreparer with a caller-chosen X-User-ID (recorded as
    prepared_by_user_id / filed_by_user_id on bonded reports)."""
    return build_user_headers(user_id, UserRole.BONDED_PREPARER.value)


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer with a caller-chosen X-User-ID. Pass an id different
    from the filer's for a clean decision; pass the filer's id to exercise
    the segregation-of-duties rejection."""
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)
