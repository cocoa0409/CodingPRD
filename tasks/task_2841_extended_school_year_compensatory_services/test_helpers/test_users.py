"""Pre-built request headers for each acting role.

The PRD requires every request to carry `X-User-ID` and `X-User-Role`. Four of
the six roles are backed by opaque staff identifiers; the other two are
entity-backed and must be built per test from the acting entity's own `id`:
a `RelatedServiceProvider` acts as a `Provider`, and a `ParentGuardian` acts as
a `Student`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CASE_MANAGER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PARENT_GUARDIAN,
    ROLE_PROGRAM_COORDINATOR,
    ROLE_RELATED_SERVICE_PROVIDER,
    ROLE_SPED_DIRECTOR,
)

CASE_MANAGER_USER_ID = "cm-001"
CASE_MANAGER_ALT_USER_ID = "cm-002"
PROGRAM_COORDINATOR_USER_ID = "pc-001"
SPED_DIRECTOR_USER_ID = "dir-001"
SPED_DIRECTOR_ALT_USER_ID = "dir-002"
COMPLIANCE_OFFICER_USER_ID = "co-001"


def make_case_manager_headers(user_id: str = CASE_MANAGER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CASE_MANAGER)


def make_program_coordinator_headers(
    user_id: str = PROGRAM_COORDINATOR_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PROGRAM_COORDINATOR)


def make_sped_director_headers(
    user_id: str = SPED_DIRECTOR_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_SPED_DIRECTOR)


def make_compliance_officer_headers(
    user_id: str = COMPLIANCE_OFFICER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_related_service_provider_headers(provider_id: str) -> Dict[str, str]:
    """Headers for a provider acting on their own resources.

    `X-User-ID` must be the acting `Provider`'s `id`.
    """
    return build_user_headers(provider_id, ROLE_RELATED_SERVICE_PROVIDER)


def make_parent_guardian_headers(student_id: str) -> Dict[str, str]:
    """Headers for a guardian acting on their own child's resources.

    `X-User-ID` must be the acting `Student`'s `id`.
    """
    return build_user_headers(student_id, ROLE_PARENT_GUARDIAN)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    return build_user_headers(user_id, role)


TEST_USERS: Dict[str, Dict[str, str]] = {
    "case_manager": make_case_manager_headers(),
    "case_manager_alt": make_case_manager_headers(CASE_MANAGER_ALT_USER_ID),
    "program_coordinator": make_program_coordinator_headers(),
    "sped_director": make_sped_director_headers(),
    "sped_director_alt": make_sped_director_headers(SPED_DIRECTOR_ALT_USER_ID),
    "compliance_officer": make_compliance_officer_headers(),
}
