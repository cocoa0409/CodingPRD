"""Pre-built role headers for every role in the PRD (§2.1).

LeagueAdmin and PublicUser are opaque identities: the server never compares
their X-User-ID to any entity id, so shared constants are canonical.

The five volunteer-backed roles and Candidate are entity-backed: X-User-ID
must be the id of the acting Volunteer (carrying the mapped capability) or
CandidateFiling.  For those, the make_*_headers builders are the canonical
form — call them with the real entity id once the fixture has created it.
"""
from prd_bench_local_runner.testing import build_user_headers

ROLE_LEAGUE_ADMIN = "LeagueAdmin"
ROLE_COORDINATOR = "ChapterCoordinator"
ROLE_EDITOR = "QuestionnaireEditor"
ROLE_REVIEWER = "NeutralityReviewer"
ROLE_MODERATOR = "ForumModerator"
ROLE_CANDIDATE = "Candidate"
ROLE_PUBLIC = "PublicUser"

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "admin_headers": build_user_headers("test-admin-1", ROLE_LEAGUE_ADMIN),
    "public_headers": build_user_headers("test-public-1", ROLE_PUBLIC),
    # Entity-backed fallbacks — ONLY for tests whose outcome does not depend
    # on the caller owning or backing a real entity (e.g. 400/404 probes).
    "coordinator_headers": build_user_headers("test-coordinator-1", ROLE_COORDINATOR),
    "editor_headers": build_user_headers("test-editor-1", ROLE_EDITOR),
    "reviewer_headers": build_user_headers("test-reviewer-1", ROLE_REVIEWER),
    "moderator_headers": build_user_headers("test-moderator-1", ROLE_MODERATOR),
    "candidate_headers": build_user_headers("test-candidate-1", ROLE_CANDIDATE),
}


def make_coordinator_headers(volunteer_id: str) -> dict:
    """ChapterCoordinator is entity-backed by a Volunteer with COORDINATOR."""
    return build_user_headers(volunteer_id, ROLE_COORDINATOR)


def make_editor_headers(volunteer_id: str) -> dict:
    """QuestionnaireEditor is entity-backed by a Volunteer with EDITOR."""
    return build_user_headers(volunteer_id, ROLE_EDITOR)


def make_reviewer_headers(volunteer_id: str) -> dict:
    """NeutralityReviewer is entity-backed by a Volunteer with REVIEWER."""
    return build_user_headers(volunteer_id, ROLE_REVIEWER)


def make_moderator_headers(volunteer_id: str) -> dict:
    """ForumModerator is entity-backed by a Volunteer with MODERATOR."""
    return build_user_headers(volunteer_id, ROLE_MODERATOR)


def make_candidate_headers(filing_id: str) -> dict:
    """Candidate is entity-backed by a CandidateFiling; X-User-ID = filing id."""
    return build_user_headers(filing_id, ROLE_CANDIDATE)
