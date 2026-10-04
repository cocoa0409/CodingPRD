"""Pre-built role headers for every role in the PRD (§2.1).

ProgramAdmin is an opaque role (X-User-ID is never compared to an entity id),
so its shared constant is canonical. The other four roles are entity-backed:
SchoolOfficial is the acting School's id, Student the acting Student's id,
SponsorAdmin the acting CorporateSponsor's id, CollegeAdmin the acting
CollegeInstitution's id. Any ownership-gated call MUST use the matching
make_*_headers() builder with the real entity id; the shared constants for
those roles are fallbacks for non-ownership tests only (bad-payload 400s,
missing-resource 404s, role-matrix 403s).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role — canonical shared form.
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    # Entity-backed roles — fallback for non-ownership tests only.
    "school_official_headers": build_user_headers("test-school-official-1", "SchoolOfficial"),
    "student_headers": build_user_headers("test-student-1", "Student"),
    "sponsor_admin_headers": build_user_headers("test-sponsor-admin-1", "SponsorAdmin"),
    "college_admin_headers": build_user_headers("test-college-admin-1", "CollegeAdmin"),
}


def make_school_official_headers(school_id: str) -> dict:
    """SchoolOfficial is entity-backed by School: X-User-ID must equal the
    acting school's id for endorsement (PRD §2.1)."""
    return build_user_headers(school_id, "SchoolOfficial")


def make_student_headers(student_id: str) -> dict:
    """Student is entity-backed by Student: X-User-ID must equal the acting
    student's id on entry creation, application create/submit, and award
    accept/decline (PRD §2.1)."""
    return build_user_headers(student_id, "Student")


def make_sponsor_admin_headers(sponsor_id: str) -> dict:
    """SponsorAdmin is entity-backed by CorporateSponsor: X-User-ID must equal
    the acting sponsor's id on agreement create/amend (PRD §2.1)."""
    return build_user_headers(sponsor_id, "SponsorAdmin")


def make_college_admin_headers(college_id: str) -> dict:
    """CollegeAdmin is entity-backed by CollegeInstitution: X-User-ID must
    equal the funding institution's id on renewal submission (PRD §2.1)."""
    return build_user_headers(college_id, "CollegeAdmin")


__all__ = [
    "TEST_USERS",
    "make_school_official_headers",
    "make_student_headers",
    "make_sponsor_admin_headers",
    "make_college_admin_headers",
]
