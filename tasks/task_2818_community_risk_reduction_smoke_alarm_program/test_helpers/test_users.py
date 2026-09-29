"""Identity headers for every role in the program.

The PRD requires both ``X-User-ID`` and ``X-User-Role`` on every request. Two
roles are entity-backed: a ``CrrTechnician`` presents the crew's ``id`` and a
``PartnerLiaison`` presents the partner organisation's ``id``. The remaining four
roles are opaque principals, so any stable identifier works for them.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import Role

# Opaque principals reused across the suite.
PROGRAM_ADMIN_ID = "admin-1"
RISK_ANALYST_ID = "analyst-1"
CANVASS_COORDINATOR_ID = "coordinator-1"
GRANT_OFFICER_ID = "officer-1"

# Distinct grant officers so that compile and submit can be separated when the
# PRD's separation-of-duties rule requires two different people.
GRANT_OFFICER_COMPILE_ID = "officer-compile-1"
GRANT_OFFICER_SUBMIT_ID = "officer-submit-2"

TEST_USERS: Dict[str, Dict[str, str]] = {
    Role.PROGRAM_ADMIN: build_user_headers(PROGRAM_ADMIN_ID, Role.PROGRAM_ADMIN),
    Role.RISK_ANALYST: build_user_headers(RISK_ANALYST_ID, Role.RISK_ANALYST),
    Role.CANVASS_COORDINATOR: build_user_headers(
        CANVASS_COORDINATOR_ID, Role.CANVASS_COORDINATOR
    ),
    Role.GRANT_OFFICER: build_user_headers(GRANT_OFFICER_ID, Role.GRANT_OFFICER),
}

# Convenience aliases.
ADMIN = TEST_USERS[Role.PROGRAM_ADMIN]
ANALYST = TEST_USERS[Role.RISK_ANALYST]
COORDINATOR = TEST_USERS[Role.CANVASS_COORDINATOR]
OFFICER = TEST_USERS[Role.GRANT_OFFICER]


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.PROGRAM_ADMIN)


def make_risk_analyst_headers(user_id: str = RISK_ANALYST_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.RISK_ANALYST)


def make_canvass_coordinator_headers(
    user_id: str = CANVASS_COORDINATOR_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.CANVASS_COORDINATOR)


def make_grant_officer_headers(user_id: str = GRANT_OFFICER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.GRANT_OFFICER)


def make_crr_technician_headers(crew_id: str) -> Dict[str, str]:
    """A field technician authenticates as the crew whose ``id`` this is."""
    return build_user_headers(crew_id, Role.CRR_TECHNICIAN)


def make_partner_liaison_headers(partner_id: str) -> Dict[str, str]:
    """A liaison authenticates as the partner organisation whose ``id`` this is."""
    return build_user_headers(partner_id, Role.PARTNER_LIAISON)


def headers_for(role: str, user_id: str) -> Dict[str, str]:
    """Build headers for an arbitrary role/principal pair."""
    return build_user_headers(user_id, role)


def headers_missing_role(user_id: str = PROGRAM_ADMIN_ID) -> Dict[str, str]:
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_missing_user_id(role: str = Role.PROGRAM_ADMIN) -> Dict[str, str]:
    return {"X-User-Role": role, "Content-Type": "application/json"}


NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
