"""Pre-built role headers for every role in the PRD.

Five of the six roles carry an opaque operator identifier that the server merely
records on the rows they touch, so a shared constant is the canonical form for
them. A `YouthMember`'s `X-User-ID` **is** the `id` of the acting `Youth`, so
every ownership-gated youth call must use ``make_youth_member_headers`` with the
real youth id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Distinct operator identifiers. Segregation-of-duties rules compare recorded
# identifiers against each other, so paired operations need two different ids.
USER_IDS = {
    "OUTREACH_WORKER": "worker-1",
    "OUTREACH_WORKER_ALT": "worker-7",
    "SHELTER_CASE_MANAGER": "cm-1",
    "SHELTER_CASE_MANAGER_ALT": "cm-7",
    "REUNIFICATION_SPECIALIST": "rs-1",
    "REUNIFICATION_SPECIALIST_ALT": "rs-2",
    "REUNIFICATION_SPECIALIST_THIRD": "spec-7",
    "REUNIFICATION_SPECIALIST_FOURTH": "spec-8",
    "TLP_COORDINATOR": "tlp-1",
    "TLP_COORDINATOR_ALT": "tlp-2",
    "PROGRAM_ADMIN": "admin-1",
    "PROGRAM_ADMIN_ALT": "admin-2",
}


TEST_USERS: Dict[str, Dict[str, str]] = {
    "outreach_worker_headers": build_user_headers(
        USER_IDS["OUTREACH_WORKER"], UserRole.OUTREACH_WORKER.value
    ),
    "outreach_worker_alt_headers": build_user_headers(
        USER_IDS["OUTREACH_WORKER_ALT"], UserRole.OUTREACH_WORKER.value
    ),
    "shelter_case_manager_headers": build_user_headers(
        USER_IDS["SHELTER_CASE_MANAGER"], UserRole.SHELTER_CASE_MANAGER.value
    ),
    "shelter_case_manager_alt_headers": build_user_headers(
        USER_IDS["SHELTER_CASE_MANAGER_ALT"], UserRole.SHELTER_CASE_MANAGER.value
    ),
    "reunification_specialist_headers": build_user_headers(
        USER_IDS["REUNIFICATION_SPECIALIST"], UserRole.REUNIFICATION_SPECIALIST.value
    ),
    "reunification_specialist_alt_headers": build_user_headers(
        USER_IDS["REUNIFICATION_SPECIALIST_ALT"], UserRole.REUNIFICATION_SPECIALIST.value
    ),
    "tlp_coordinator_headers": build_user_headers(
        USER_IDS["TLP_COORDINATOR"], UserRole.TLP_COORDINATOR.value
    ),
    "tlp_coordinator_alt_headers": build_user_headers(
        USER_IDS["TLP_COORDINATOR_ALT"], UserRole.TLP_COORDINATOR.value
    ),
    "program_admin_headers": build_user_headers(
        USER_IDS["PROGRAM_ADMIN"], UserRole.PROGRAM_ADMIN.value
    ),
    "program_admin_alt_headers": build_user_headers(
        USER_IDS["PROGRAM_ADMIN_ALT"], UserRole.PROGRAM_ADMIN.value
    ),
}


def make_outreach_worker_headers(user_id: str) -> Dict[str, str]:
    """Headers for an `OutreachWorker` acting under a specific operator id."""
    return build_user_headers(user_id, UserRole.OUTREACH_WORKER.value)


def make_shelter_case_manager_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `ShelterCaseManager` acting under a specific operator id."""
    return build_user_headers(user_id, UserRole.SHELTER_CASE_MANAGER.value)


def make_reunification_specialist_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `ReunificationSpecialist` acting under a specific operator id."""
    return build_user_headers(user_id, UserRole.REUNIFICATION_SPECIALIST.value)


def make_tlp_coordinator_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `TlpCoordinator` acting under a specific operator id."""
    return build_user_headers(user_id, UserRole.TLP_COORDINATOR.value)


def make_program_admin_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `ProgramAdmin` acting under a specific operator id."""
    return build_user_headers(user_id, UserRole.PROGRAM_ADMIN.value)


def make_youth_member_headers(youth_id: str) -> Dict[str, str]:
    """Headers for a `YouthMember`; pass the acting youth's own `id`.

    A `YouthMember` may read only the youth record whose `id` equals its own
    `X-User-ID`, so this builder is mandatory for every governance and
    own-record call.
    """
    return build_user_headers(youth_id, UserRole.YOUTH_MEMBER.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for auth tests that need an arbitrary id/role pair,
    including an empty string for either header."""
    return build_user_headers(user_id, role)
