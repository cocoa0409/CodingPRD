"""Pre-built role headers for every role in the PRD.

`FacultyMentor` and `Postdoc` identify a stored record through `X-User-ID`, so
every ownership-gated call must be made with the per-instance builders below,
passing the real record's `id`. The other four roles carry an opaque operator
identifier that is never compared to any row's `id`.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

# ─── Opaque operator identifiers ──────────────────────────────────────────
# Distinct values so that segregation-of-duties separations are satisfiable:
# the preparing officer, the finalizing officer, the compensation approver and
# the screening reviewer must all be different people.
OFFICER_USER_ID = "officer-pa-1"
OFFICER_ALT_USER_ID = "officer-pa-2"
HR_APPROVER_USER_ID = "hr-approver-1"
HR_APPROVER_ALT_USER_ID = "hr-approver-2"
EXPORT_REVIEWER_USER_ID = "export-reviewer-1"
EXPORT_REVIEWER_ALT_USER_ID = "export-reviewer-2"
SCHOLAR_ADVISOR_USER_ID = "scholar-advisor-1"

# Shared constants — safe for the four opaque roles, and for any test whose
# success does not depend on the caller owning the subject record.
TEST_USERS: Dict[str, dict] = {
    "officer_headers": build_user_headers(OFFICER_USER_ID, "PostdocAffairsOfficer"),
    "officer_alt_headers": build_user_headers(OFFICER_ALT_USER_ID, "PostdocAffairsOfficer"),
    "hr_approver_headers": build_user_headers(HR_APPROVER_USER_ID, "HRCompensationApprover"),
    "hr_approver_alt_headers": build_user_headers(
        HR_APPROVER_ALT_USER_ID, "HRCompensationApprover"
    ),
    "export_reviewer_headers": build_user_headers(
        EXPORT_REVIEWER_USER_ID, "ExportControlReviewer"
    ),
    "export_reviewer_alt_headers": build_user_headers(
        EXPORT_REVIEWER_ALT_USER_ID, "ExportControlReviewer"
    ),
    "scholar_advisor_headers": build_user_headers(
        SCHOLAR_ADVISOR_USER_ID, "InternationalScholarAdvisor"
    ),
    # The two entity-backed roles: these shared constants are a fallback for
    # reads and for tests that never reach an ownership comparison.
    "faculty_mentor_headers": build_user_headers("mentor-placeholder-1", "FacultyMentor"),
    "postdoc_headers": build_user_headers("postdoc-placeholder-1", "Postdoc"),
}

# The six declared role strings, in the order the PRD lists them.
ALL_ROLE_HEADER_KEYS = [
    "PostdocAffairsOfficer",
    "HRCompensationApprover",
    "ExportControlReviewer",
    "InternationalScholarAdvisor",
    "FacultyMentor",
    "Postdoc",
]


# ─── Per-instance builders for the two entity-backed roles ────────────────

def make_faculty_mentor_headers(user_id: str) -> dict:
    """For `FacultyMentor`. Pass the acting mentor record's `id` as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "FacultyMentor")


def make_postdoc_headers(user_id: str) -> dict:
    """For `Postdoc`. Pass the acting scholar record's `id` as user_id whenever
    the call is ownership-gated."""
    return build_user_headers(user_id, "Postdoc")


def make_officer_headers(user_id: str = OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, "PostdocAffairsOfficer")


def make_hr_approver_headers(user_id: str = HR_APPROVER_USER_ID) -> dict:
    return build_user_headers(user_id, "HRCompensationApprover")


def make_export_reviewer_headers(user_id: str = EXPORT_REVIEWER_USER_ID) -> dict:
    return build_user_headers(user_id, "ExportControlReviewer")


def make_scholar_advisor_headers(user_id: str = SCHOLAR_ADVISOR_USER_ID) -> dict:
    return build_user_headers(user_id, "InternationalScholarAdvisor")


def make_headers_for_role(role: str, user_id: str) -> dict:
    """Build headers for an arbitrary role string, including undeclared ones."""
    return build_user_headers(user_id, role)


# ─── Deliberately defective header sets ───────────────────────────────────

def headers_without_role(user_id: str = OFFICER_USER_ID) -> dict:
    """`X-User-ID` present, `X-User-Role` omitted."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = "PostdocAffairsOfficer") -> dict:
    """`X-User-Role` present, `X-User-ID` omitted."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_undeclared_role(user_id: str = "registrar-1",
                                 role: str = "Registrar") -> dict:
    """Both headers present but the role is not one of the six declared strings."""
    return build_user_headers(user_id, role)


def all_role_headers(mentor_id: Optional[str] = None,
                     postdoc_id: Optional[str] = None) -> Dict[str, dict]:
    """Headers for all six roles, threading real identities where supplied."""
    return {
        "PostdocAffairsOfficer": TEST_USERS["officer_headers"],
        "HRCompensationApprover": TEST_USERS["hr_approver_headers"],
        "ExportControlReviewer": TEST_USERS["export_reviewer_headers"],
        "InternationalScholarAdvisor": TEST_USERS["scholar_advisor_headers"],
        "FacultyMentor": (
            make_faculty_mentor_headers(mentor_id) if mentor_id
            else TEST_USERS["faculty_mentor_headers"]
        ),
        "Postdoc": (
            make_postdoc_headers(postdoc_id) if postdoc_id
            else TEST_USERS["postdoc_headers"]
        ),
    }
