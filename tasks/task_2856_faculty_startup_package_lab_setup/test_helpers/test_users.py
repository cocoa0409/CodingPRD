"""Pre-built role headers for the five roles named in the PRD.

DeanOffice and FacilitiesManager carry opaque operator identifiers, so the
shared constants below are the canonical form for them.  DepartmentChair and
Dean are backed by a FundingUnit and Faculty is backed by a Faculty record, so
ownership-gated calls for those three roles MUST use the per-instance builders.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import TEST_DEFAULTS

# Shared constants. Safe for the two opaque roles, and for tests whose success
# does not depend on the caller owning the subject resource.
TEST_USERS = {
    "dean_office_headers": build_user_headers(
        TEST_DEFAULTS["DEAN_OFFICE_USER_ID"], "DeanOffice"
    ),
    "facilities_manager_headers": build_user_headers(
        TEST_DEFAULTS["FACILITIES_USER_ID"], "FacilitiesManager"
    ),
    # Entity-backed roles: fallbacks for non-ownership tests only.
    "department_chair_headers": build_user_headers("U-CHAIR-UNKNOWN", "DepartmentChair"),
    "dean_headers": build_user_headers("U-DEAN-UNKNOWN", "Dean"),
    "faculty_headers": build_user_headers("U-FACULTY-UNKNOWN", "Faculty"),
}


def make_dean_office_headers(user_id: str = None) -> dict:
    """For DeanOffice, whose X-User-ID is an opaque operator identifier that the
    server records as proposed_by_user_id on submit."""
    return build_user_headers(user_id or TEST_DEFAULTS["DEAN_OFFICE_USER_ID"], "DeanOffice")


def make_facilities_manager_headers(user_id: str = None) -> dict:
    """For FacilitiesManager, whose X-User-ID is an opaque operator identifier."""
    return build_user_headers(
        user_id or TEST_DEFAULTS["FACILITIES_USER_ID"], "FacilitiesManager"
    )


def make_department_chair_headers(funding_unit_id: str) -> dict:
    """For DepartmentChair: pass the acting DEPARTMENT FundingUnit id, which
    ownership checks compare against the package's department_unit_id."""
    return build_user_headers(funding_unit_id, "DepartmentChair")


def make_dean_headers(funding_unit_id: str) -> dict:
    """For Dean: pass the acting COLLEGE FundingUnit id, which ownership checks
    compare against the package's college_unit_id."""
    return build_user_headers(funding_unit_id, "Dean")


def make_faculty_headers(faculty_id: str) -> dict:
    """For Faculty: pass the acting Faculty record id, which ownership checks
    compare against the resource's faculty_id."""
    return build_user_headers(faculty_id, "Faculty")


def make_role_only_headers(role: str) -> dict:
    """Headers that declare a role but deliberately omit X-User-ID."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
