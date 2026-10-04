"""Pre-built role headers for every role the PRD declares.

Three roles are entity-backed: a SchoolCoordinator's X-User-ID is the id of the
acting School, a Reader's is the id of the acting Reader and a SchoolStudent's
is the id of the acting Student. Calls made by those roles must build their
headers per instance with the make_*_headers() helpers below; the shared
constants exist only for calls that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identities. Several distinct ids per role so that
# segregation-of-duties tests can act as a second operator who did not
# originate the record under review.
PLATFORM_ADMIN = "admin-1"
PLATFORM_ADMIN_2 = "admin-2"
COURSE_AUDIT_REVIEWER = "reviewer-1"
COURSE_AUDIT_REVIEWER_2 = "reviewer-2"
ACCOMMODATION_REVIEWER = "accom-reviewer-1"
ACCOMMODATION_REVIEWER_2 = "accom-reviewer-2"
SCORING_SPECIALIST = "spec-1"
SCORING_SPECIALIST_2 = "spec-2"
INTEGRITY_INVESTIGATOR = "investigator-1"
INTEGRITY_INVESTIGATOR_2 = "investigator-2"

ALL_ROLES = [
    "PlatformAdmin",
    "SchoolCoordinator",
    "CourseAuditReviewer",
    "AccommodationReviewer",
    "ScoringSpecialist",
    "IntegrityInvestigator",
    "Reader",
    "SchoolStudent",
]

TEST_USERS = {
    # Opaque roles: the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN, "PlatformAdmin"),
    "platform_admin_2_headers": build_user_headers(PLATFORM_ADMIN_2, "PlatformAdmin"),
    "course_audit_reviewer_headers": build_user_headers(
        COURSE_AUDIT_REVIEWER, "CourseAuditReviewer"
    ),
    "course_audit_reviewer_2_headers": build_user_headers(
        COURSE_AUDIT_REVIEWER_2, "CourseAuditReviewer"
    ),
    "accommodation_reviewer_headers": build_user_headers(
        ACCOMMODATION_REVIEWER, "AccommodationReviewer"
    ),
    "accommodation_reviewer_2_headers": build_user_headers(
        ACCOMMODATION_REVIEWER_2, "AccommodationReviewer"
    ),
    "scoring_specialist_headers": build_user_headers(SCORING_SPECIALIST, "ScoringSpecialist"),
    "scoring_specialist_2_headers": build_user_headers(SCORING_SPECIALIST_2, "ScoringSpecialist"),
    "integrity_investigator_headers": build_user_headers(
        INTEGRITY_INVESTIGATOR, "IntegrityInvestigator"
    ),
    "integrity_investigator_2_headers": build_user_headers(
        INTEGRITY_INVESTIGATOR_2, "IntegrityInvestigator"
    ),
    # Entity-backed roles: fallback only, never for an ownership-gated call.
    "school_coordinator_headers": build_user_headers("school-unbound", "SchoolCoordinator"),
    "reader_headers": build_user_headers("reader-unbound", "Reader"),
    "school_student_headers": build_user_headers("student-unbound", "SchoolStudent"),
}


def make_school_coordinator_headers(school_id: str) -> dict:
    """A SchoolCoordinator's X-User-ID is the id of the acting School."""
    return build_user_headers(school_id, "SchoolCoordinator")


def make_reader_headers(reader_id: str) -> dict:
    """A Reader's X-User-ID is the id of the acting Reader."""
    return build_user_headers(reader_id, "Reader")


def make_school_student_headers(student_id: str) -> dict:
    """A SchoolStudent's X-User-ID is the id of the acting Student."""
    return build_user_headers(student_id, "SchoolStudent")


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_course_audit_reviewer_headers(user_id: str = COURSE_AUDIT_REVIEWER) -> dict:
    return build_user_headers(user_id, "CourseAuditReviewer")


def make_accommodation_reviewer_headers(user_id: str = ACCOMMODATION_REVIEWER) -> dict:
    return build_user_headers(user_id, "AccommodationReviewer")


def make_scoring_specialist_headers(user_id: str = SCORING_SPECIALIST) -> dict:
    return build_user_headers(user_id, "ScoringSpecialist")


def make_integrity_investigator_headers(user_id: str = INTEGRITY_INVESTIGATOR) -> dict:
    return build_user_headers(user_id, "IntegrityInvestigator")
