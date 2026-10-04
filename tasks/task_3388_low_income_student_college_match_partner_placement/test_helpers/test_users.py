"""Pre-built role headers for every role in the PRD.

Identity model (PRD §2.1):
- Student        → X-User-ID is the acting Student.id          (entity-backed)
- Counselor      → X-User-ID is the acting Counselor.id        (entity-backed)
- PartnerStaff   → X-User-ID is the acting CommunityPartner.id (entity-backed)
- CollegeOfficer → X-User-ID is the serving PartnerCollege.id  (entity-backed)
- ProgramAdmin   → opaque operator id, never compared to any entity
- Anonymous      → no X-User-ID required at all

The TEST_USERS constants are only for calls whose success does NOT depend on
the caller owning the subject resource. Any ownership-gated call MUST use the
per-instance builder with the real entity id (e.g. make_student_headers(
student["id"])); reusing a shared constant for an entity-backed role makes
every ownership check reject the request.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole


def _role_only_headers(role: str) -> dict:
    return {"X-User-Role": role, "Content-Type": "application/json"}


# Shared constants — opaque roles are canonical; entity-backed entries are
# fallbacks for non-ownership tests only (400/404/role-denied probes).
TEST_USERS = {
    "program_admin_headers": build_user_headers(
        "test-program-admin-1", UserRole.PROGRAM_ADMIN.value
    ),
    "student_headers": build_user_headers(
        "test-student-1", UserRole.STUDENT.value
    ),
    "counselor_headers": build_user_headers(
        "test-counselor-1", UserRole.COUNSELOR.value
    ),
    "partner_staff_headers": build_user_headers(
        "test-partner-1", UserRole.PARTNER_STAFF.value
    ),
    "college_officer_headers": build_user_headers(
        "test-college-1", UserRole.COLLEGE_OFFICER.value
    ),
    # Anonymous needs no X-User-ID; this is the canonical anonymous shape.
    "anonymous_headers": _role_only_headers(UserRole.ANONYMOUS.value),
}


# --- Per-instance builders (required for every entity-backed role) ----------

def make_student_headers(student_id: str) -> dict:
    """Student is entity_backed:Student — pass the real Student.id for any
    ownership-gated call (applications, rankings, withdraw, enroll)."""
    return build_user_headers(student_id, UserRole.STUDENT.value)


def make_counselor_headers(counselor_id: str) -> dict:
    """Counselor is entity_backed:Counselor — pass the real Counselor.id."""
    return build_user_headers(counselor_id, UserRole.COUNSELOR.value)


def make_partner_staff_headers(community_partner_id: str) -> dict:
    """PartnerStaff is entity_backed:CommunityPartner — X-User-ID is the
    CommunityPartner.id (the organization, not a person)."""
    return build_user_headers(community_partner_id, UserRole.PARTNER_STAFF.value)


def make_college_officer_headers(partner_college_id: str) -> dict:
    """CollegeOfficer is entity_backed:PartnerCollege — X-User-ID is the
    PartnerCollege.id the officer serves."""
    return build_user_headers(partner_college_id, UserRole.COLLEGE_OFFICER.value)


def make_program_admin_headers(operator_id: str = "test-program-admin-1") -> dict:
    """ProgramAdmin identity is opaque; the id is never compared to entities."""
    return build_user_headers(operator_id, UserRole.PROGRAM_ADMIN.value)


def make_anonymous_headers() -> dict:
    """Anonymous sends no X-User-ID at all."""
    return _role_only_headers(UserRole.ANONYMOUS.value)
