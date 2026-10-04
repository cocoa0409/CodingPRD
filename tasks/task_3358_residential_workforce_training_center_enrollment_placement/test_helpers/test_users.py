"""Pre-built role headers for every role in the PRD (section 2.1).

All seven roles use opaque operator identities: X-User-ID is an operator string
never compared to any persisted entity's id. Shared constants are therefore the
canonical form. Per-call builders are provided for segregation-of-duties flows
where the caller's identity string itself matters (intake counselor vs reviewer).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import COUNSELOR_USER_ID, REVIEWER_USER_ID
from .types import UserRole

TEST_USERS = {
    "admissions_counselor_headers": build_user_headers(
        COUNSELOR_USER_ID, UserRole.ADMISSIONS_COUNSELOR.value
    ),
    "eligibility_reviewer_headers": build_user_headers(
        REVIEWER_USER_ID, UserRole.ELIGIBILITY_REVIEWER.value
    ),
    "enrollment_manager_headers": build_user_headers(
        "manager-1", UserRole.ENROLLMENT_MANAGER.value
    ),
    "residential_advisor_headers": build_user_headers(
        "advisor-1", UserRole.RESIDENTIAL_ADVISOR.value
    ),
    "career_instructor_headers": build_user_headers(
        "instructor-1", UserRole.CAREER_INSTRUCTOR.value
    ),
    "transition_specialist_headers": build_user_headers(
        "specialist-1", UserRole.TRANSITION_SPECIALIST.value
    ),
    "operator_admin_headers": build_user_headers(
        "admin-1", UserRole.OPERATOR_ADMIN.value
    ),
}


def make_counselor_headers(user_id: str) -> dict:
    """AdmissionsCounselor headers with a specific opaque identity string."""
    return build_user_headers(user_id, UserRole.ADMISSIONS_COUNSELOR.value)


def make_reviewer_headers(user_id: str) -> dict:
    """EligibilityReviewer headers with a specific opaque identity string."""
    return build_user_headers(user_id, UserRole.ELIGIBILITY_REVIEWER.value)
