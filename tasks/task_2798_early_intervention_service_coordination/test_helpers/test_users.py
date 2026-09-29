"""
Role identities and auth headers.

Four roles carry an opaque operator identifier that the server never compares to
an entity id: ``IntakeSpecialist``, ``ProgramAdmin``, ``Evaluator`` and
``FiscalOfficer``. For those, the shared constants below are safe.

Three roles are entity-backed and their ``X-User-ID`` drives ownership checks:
``ServiceCoordinator`` must carry a ServiceCoordinator id, ``Provider`` a
Provider id, and ``FamilyRepresentative`` a Child id. Never use a shared
constant for those three — always mint headers from the real entity id with the
``make_*_headers`` helpers.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# ─── Role names, spelled exactly as the contract requires ─────────────
ROLE_INTAKE_SPECIALIST = "IntakeSpecialist"
ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_EVALUATOR = "Evaluator"
ROLE_FISCAL_OFFICER = "FiscalOfficer"
ROLE_SERVICE_COORDINATOR = "ServiceCoordinator"
ROLE_PROVIDER = "Provider"
ROLE_FAMILY_REPRESENTATIVE = "FamilyRepresentative"

# ─── Opaque operator identifiers ──────────────────────────────────────
INTAKE_SPECIALIST_USER_ID = "intake-specialist-1"
PROGRAM_ADMIN_USER_ID = "program-admin-1"
EVALUATOR_USER_ID = "evaluator-1"
EVALUATOR_2_USER_ID = "evaluator-2"

# Cost participation is subject to segregation of duties, so two distinct
# fiscal identities are always needed: one determines, another waives.
FISCAL_OFFICER_USER_ID = "fiscal-officer-1"
FISCAL_OFFICER_2_USER_ID = "fiscal-officer-2"

TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_INTAKE_SPECIALIST: build_user_headers(
        INTAKE_SPECIALIST_USER_ID, ROLE_INTAKE_SPECIALIST
    ),
    ROLE_PROGRAM_ADMIN: build_user_headers(
        PROGRAM_ADMIN_USER_ID, ROLE_PROGRAM_ADMIN
    ),
    ROLE_EVALUATOR: build_user_headers(EVALUATOR_USER_ID, ROLE_EVALUATOR),
    ROLE_FISCAL_OFFICER: build_user_headers(
        FISCAL_OFFICER_USER_ID, ROLE_FISCAL_OFFICER
    ),
}

INTAKE_HEADERS = TEST_USERS[ROLE_INTAKE_SPECIALIST]
ADMIN_HEADERS = TEST_USERS[ROLE_PROGRAM_ADMIN]
EVALUATOR_HEADERS = TEST_USERS[ROLE_EVALUATOR]
FISCAL_HEADERS = TEST_USERS[ROLE_FISCAL_OFFICER]
FISCAL_2_HEADERS = build_user_headers(
    FISCAL_OFFICER_2_USER_ID, ROLE_FISCAL_OFFICER
)


# ─── Entity-backed identities ─────────────────────────────────────────

def make_service_coordinator_headers(coordinator_id: str) -> Dict[str, str]:
    """Headers for the coordinator whose ServiceCoordinator id is given."""
    return build_user_headers(coordinator_id, ROLE_SERVICE_COORDINATOR)


def make_provider_headers(provider_id: str) -> Dict[str, str]:
    """Headers for the agency whose Provider id is given."""
    return build_user_headers(provider_id, ROLE_PROVIDER)


def make_family_representative_headers(child_id: str) -> Dict[str, str]:
    """Headers for the parent of the Child whose id is given."""
    return build_user_headers(child_id, ROLE_FAMILY_REPRESENTATIVE)


def make_evaluator_headers(user_id: str = EVALUATOR_USER_ID) -> Dict[str, str]:
    """Headers for a named Evaluator operator identity."""
    return build_user_headers(user_id, ROLE_EVALUATOR)


def make_fiscal_officer_headers(
    user_id: str = FISCAL_OFFICER_USER_ID,
) -> Dict[str, str]:
    """Headers for a named FiscalOfficer operator identity."""
    return build_user_headers(user_id, ROLE_FISCAL_OFFICER)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Well-formed headers with ``X-User-ID`` omitted entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Well-formed headers with ``X-User-Role`` omitted entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
