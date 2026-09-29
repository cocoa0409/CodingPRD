"""
Pre-built auth headers for each of the seven roles.

PRD 2.1: "Every request must carry two headers: `X-User-ID`, identifying the
acting user, and `X-User-Role`, declaring the capacity in which they act."

Six of the seven roles carry an opaque operator identifier, so a fixed literal
per role is enough. `ProgramLead` is different: its `X-User-ID` is the id of the
acting `BreedingProgram`, so its headers can only be built once a programme
exists — use ``make_program_lead_headers(program_id)``.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# ─── Opaque operator identities ───────────────────────

DIRECTOR_USER_ID = "pd-1"
SCIENTIST_USER_ID = "bs-1"
AGRONOMIST_USER_ID = "ta-1"
ANALYST_USER_ID = "da-1"
REGULATORY_DRAFTER_USER_ID = "ro-1"
REGULATORY_APPROVER_USER_ID = "ro-2"
REGULATORY_THIRD_USER_ID = "ro-3"
PLANNER_USER_ID = "sp-1"

DIRECTOR_HEADERS: Dict[str, str] = build_user_headers(
    DIRECTOR_USER_ID, Role.PIPELINE_DIRECTOR
)
SCIENTIST_HEADERS: Dict[str, str] = build_user_headers(
    SCIENTIST_USER_ID, Role.BREEDING_SCIENTIST
)
AGRONOMIST_HEADERS: Dict[str, str] = build_user_headers(
    AGRONOMIST_USER_ID, Role.TRIAL_AGRONOMIST
)
ANALYST_HEADERS: Dict[str, str] = build_user_headers(
    ANALYST_USER_ID, Role.DATA_ANALYST
)
# Two distinct RegulatoryOfficer identities: PRD 3.9 forbids the approver from
# also being the suspender, so the drafter/approver split is load-bearing.
REGULATORY_HEADERS: Dict[str, str] = build_user_headers(
    REGULATORY_DRAFTER_USER_ID, Role.REGULATORY_OFFICER
)
REGULATORY_APPROVER_HEADERS: Dict[str, str] = build_user_headers(
    REGULATORY_APPROVER_USER_ID, Role.REGULATORY_OFFICER
)
REGULATORY_THIRD_HEADERS: Dict[str, str] = build_user_headers(
    REGULATORY_THIRD_USER_ID, Role.REGULATORY_OFFICER
)
PLANNER_HEADERS: Dict[str, str] = build_user_headers(
    PLANNER_USER_ID, Role.SUPPLY_PLANNER
)


def make_program_lead_headers(program_id: str) -> Dict[str, str]:
    """
    Build `ProgramLead` headers for a specific programme.

    PRD 2.1: "When `X-User-Role` is `ProgramLead`, `X-User-ID` is the `id` of
    the acting `BreedingProgram`".
    """
    return build_user_headers(program_id, Role.PROGRAM_LEAD)


def make_regulatory_headers(user_id: str) -> Dict[str, str]:
    """Build `RegulatoryOfficer` headers for an arbitrary opaque operator id."""
    return build_user_headers(user_id, Role.REGULATORY_OFFICER)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Build headers for any role/identifier pair."""
    return build_user_headers(user_id, role)


# Canonical header set per role, keyed by the exact PRD spelling. `ProgramLead`
# is absent because its identity is programme-scoped.
OPAQUE_ROLE_HEADERS: Dict[str, Dict[str, str]] = {
    Role.PIPELINE_DIRECTOR: DIRECTOR_HEADERS,
    Role.BREEDING_SCIENTIST: SCIENTIST_HEADERS,
    Role.TRIAL_AGRONOMIST: AGRONOMIST_HEADERS,
    Role.DATA_ANALYST: ANALYST_HEADERS,
    Role.REGULATORY_OFFICER: REGULATORY_HEADERS,
    Role.SUPPLY_PLANNER: PLANNER_HEADERS,
}

# Headers that must draw ERR_UNAUTHENTICATED (PRD 2.1).
NO_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": "anon-1",
    "Content-Type": "application/json",
}
NO_USER_HEADERS: Dict[str, str] = {
    "X-User-Role": Role.PIPELINE_DIRECTOR,
    "Content-Type": "application/json",
}
BAD_ROLE_HEADERS: Dict[str, str] = build_user_headers("who-1", "FieldTechnician")
