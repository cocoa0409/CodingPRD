"""Pre-built role headers for the five roles in PRD Section 2.1.

Every role's X-User-ID is an opaque operator identifier never compared
against any entity's id (PRD Section 2.1), so shared constants are the
canonical form. Two distinct HRReviewer identities exist because
segregation-of-duties compares the approver's X-User-ID against the
verified_by_hr_id stamp on credentials.
"""
from prd_bench_local_runner.testing import build_user_headers

HR_ADMIN_ID = "hr_admin_1"
HR_REVIEWER_1_ID = "hr_reviewer_1"
HR_REVIEWER_2_ID = "hr_reviewer_2"
CHAIR_ID = "chair_1"
DEAN_ID = "dean_1"
PAYROLL_OFFICER_ID = "payroll_officer_1"

TEST_USERS = {
    "hr_admin_headers": build_user_headers(HR_ADMIN_ID, "HRAdmin"),
    "hr_reviewer_1_headers": build_user_headers(HR_REVIEWER_1_ID, "HRReviewer"),
    "hr_reviewer_2_headers": build_user_headers(HR_REVIEWER_2_ID, "HRReviewer"),
    "chair_headers": build_user_headers(CHAIR_ID, "DepartmentChair"),
    "dean_headers": build_user_headers(DEAN_ID, "Dean"),
    "payroll_headers": build_user_headers(PAYROLL_OFFICER_ID, "PayrollOfficer"),
}


def make_hr_admin_headers(user_id: str = HR_ADMIN_ID) -> dict:
    return build_user_headers(user_id, "HRAdmin")


def make_hr_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HRReviewer")


def make_chair_headers(user_id: str = CHAIR_ID) -> dict:
    return build_user_headers(user_id, "DepartmentChair")


def make_dean_headers(user_id: str = DEAN_ID) -> dict:
    return build_user_headers(user_id, "Dean")


def make_payroll_headers(user_id: str = PAYROLL_OFFICER_ID) -> dict:
    return build_user_headers(user_id, "PayrollOfficer")
