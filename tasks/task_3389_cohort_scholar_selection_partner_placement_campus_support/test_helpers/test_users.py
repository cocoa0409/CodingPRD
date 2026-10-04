"""Pre-built role headers for every role in the PRD (§2.1).

Shared constants are safe for opaque roles (ProgramAdmin, Assessor,
SelectionOfficer, CareerDirector) whose X-User-ID is never compared to an
entity id, and for entity-backed roles ONLY in tests that never exercise an
ownership-gated call. For ownership-gated calls (nomination create/withdraw
as Nominator, offer accept/decline as Nominee, meeting create as
FacultyMentor, scholar self-lifecycle as Scholar) use the per-instance
builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    "assessor_a_headers": build_user_headers("assessor-a", "Assessor"),
    "assessor_b_headers": build_user_headers("assessor-b", "Assessor"),
    "selection_officer_headers": build_user_headers(
        "test-selection-officer-1", "SelectionOfficer"
    ),
    "career_director_headers": build_user_headers("test-career-director-1", "CareerDirector"),
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "nominator_headers": build_user_headers("test-nominator-1", "Nominator"),
    "nominee_headers": build_user_headers("test-nominee-1", "Nominee"),
    "faculty_mentor_headers": build_user_headers("test-faculty-mentor-1", "FacultyMentor"),
    "scholar_headers": build_user_headers("test-scholar-1", "Scholar"),
}


def make_program_admin_headers(user_id: str = "test-program-admin-1") -> dict:
    """ProgramAdmin is opaque: any identifier works, no entity comparison."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_assessor_headers(assessor_ref: str) -> dict:
    """Assessor is opaque; X-User-ID is recorded as the evaluation's
    assessor_ref and joins the (nominee_id, round_number) uniqueness key."""
    return build_user_headers(assessor_ref, "Assessor")


def make_selection_officer_headers(user_id: str = "test-selection-officer-1") -> dict:
    return build_user_headers(user_id, "SelectionOfficer")


def make_career_director_headers(user_id: str = "test-career-director-1") -> dict:
    return build_user_headers(user_id, "CareerDirector")


def make_nominator_headers(partner_id: str) -> dict:
    """Nominator is entity-backed: pass the acting NominatingPartner.id."""
    return build_user_headers(partner_id, "Nominator")


def make_nominee_headers(nominee_id: str) -> dict:
    """Nominee is entity-backed: pass the acting Nominee.id (offer.nominee_id)."""
    return build_user_headers(nominee_id, "Nominee")


def make_faculty_mentor_headers(mentor_id: str) -> dict:
    """FacultyMentor is entity-backed: pass the acting Mentor.id; meeting
    logging requires it to equal cohort.mentor_id."""
    return build_user_headers(mentor_id, "FacultyMentor")


def make_scholar_headers(scholar_id: str) -> dict:
    """Scholar is entity-backed: pass the acting Scholar.id (self only)."""
    return build_user_headers(scholar_id, "Scholar")
