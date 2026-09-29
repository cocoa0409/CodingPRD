"""Pre-built role headers for every role the program recognises.

Two of the six roles are entity-backed: a LeagueAdministrator's ``X-User-ID`` is
the id of the League it administers, and a GuardianPortal caller's ``X-User-ID``
is the id of the Participant whose guardian it is. Every ownership-gated call
MUST therefore use the matching ``make_*_headers`` builder with the real entity
id; the shared constants below are only safe for the four opaque roles and for
calls whose outcome does not depend on ownership.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Opaque identities reused across the suite.
PROGRAM_ADMIN_USER_ID = "program-admin-1"
SANCTIONING_OFFICIAL_USER_ID = "official-1"
VERIFYING_OFFICIAL_USER_ID = "official-2"
THIRD_OFFICIAL_USER_ID = "official-3"
CLAIMS_EXAMINER_USER_ID = "examiner-1"
SECOND_CLAIMS_EXAMINER_USER_ID = "examiner-2"
MEDICAL_REVIEWER_USER_ID = "reviewer-1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    # opaque roles - the shared constant is the canonical form
    "program_administrator_headers": build_user_headers(
        PROGRAM_ADMIN_USER_ID, "ProgramAdministrator"
    ),
    "league_official_headers": build_user_headers(
        SANCTIONING_OFFICIAL_USER_ID, "LeagueOfficial"
    ),
    "verifying_official_headers": build_user_headers(
        VERIFYING_OFFICIAL_USER_ID, "LeagueOfficial"
    ),
    "third_official_headers": build_user_headers(
        THIRD_OFFICIAL_USER_ID, "LeagueOfficial"
    ),
    "claims_examiner_headers": build_user_headers(
        CLAIMS_EXAMINER_USER_ID, "ClaimsExaminer"
    ),
    "second_claims_examiner_headers": build_user_headers(
        SECOND_CLAIMS_EXAMINER_USER_ID, "ClaimsExaminer"
    ),
    "medical_reviewer_headers": build_user_headers(
        MEDICAL_REVIEWER_USER_ID, "MedicalReviewer"
    ),
    # entity-backed roles - fallbacks for tests that never touch ownership
    "league_administrator_headers": build_user_headers(
        "test-league-admin-1", "LeagueAdministrator"
    ),
    "guardian_portal_headers": build_user_headers(
        "test-guardian-1", "GuardianPortal"
    ),
}


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for ProgramAdministrator (opaque identity)."""
    return build_user_headers(user_id, "ProgramAdministrator")


def make_league_admin_headers(league_id: str) -> Dict[str, str]:
    """Headers for LeagueAdministrator. ``league_id`` must be the real League.id
    the caller administers, because every league-scoped write is ownership-gated.
    """
    return build_user_headers(league_id, "LeagueAdministrator")


def make_league_official_headers(user_id: str) -> Dict[str, str]:
    """Headers for LeagueOfficial (opaque identity, recorded on the decision)."""
    return build_user_headers(user_id, "LeagueOfficial")


def make_claims_examiner_headers(
    user_id: str = CLAIMS_EXAMINER_USER_ID,
) -> Dict[str, str]:
    """Headers for ClaimsExaminer (opaque identity)."""
    return build_user_headers(user_id, "ClaimsExaminer")


def make_medical_reviewer_headers(
    user_id: str = MEDICAL_REVIEWER_USER_ID,
) -> Dict[str, str]:
    """Headers for MedicalReviewer (opaque identity)."""
    return build_user_headers(user_id, "MedicalReviewer")


def make_guardian_headers(participant_id: str) -> Dict[str, str]:
    """Headers for GuardianPortal. ``participant_id`` must be the real
    Participant.id, because guardian reads and writes are ownership-gated.
    """
    return build_user_headers(participant_id, "GuardianPortal")


ALL_ROLE_NAMES = (
    "ProgramAdministrator",
    "LeagueAdministrator",
    "LeagueOfficial",
    "ClaimsExaminer",
    "MedicalReviewer",
    "GuardianPortal",
)
