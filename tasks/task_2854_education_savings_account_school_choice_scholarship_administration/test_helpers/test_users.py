"""Header sets for every acting principal the ESA API recognises.

Six of the eight roles are staff roles whose ``X-User-ID`` is an opaque operator
identifier that is never compared against a persisted entity, so those get fixed
literals. The two entity-backed roles need a per-entity builder because
``X-User-ID`` has to be the acting student's or provider's own identifier.
"""

from prd_bench_local_runner.testing import build_user_headers

PROGRAM_ADMIN_USER_ID = "pa-1"
ELIGIBILITY_OFFICER_USER_ID = "eo-1"
EXPENSE_REVIEWER_USER_ID = "er-1"
SECOND_EXPENSE_REVIEWER_USER_ID = "er-2"
COMPLIANCE_OFFICER_USER_ID = "co-1"
APPEALS_OFFICER_USER_ID = "ao-1"
VENDOR_SCREENER_USER_ID = "vs-1"

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_ELIGIBILITY_OFFICER = "EligibilityOfficer"
ROLE_EXPENSE_REVIEWER = "ExpenseReviewer"
ROLE_VENDOR_SCREENER = "VendorScreener"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_APPEALS_OFFICER = "AppealsOfficer"
ROLE_GUARDIAN = "Guardian"
ROLE_PROVIDER = "Provider"

ALL_ROLE_NAMES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_ELIGIBILITY_OFFICER,
    ROLE_EXPENSE_REVIEWER,
    ROLE_VENDOR_SCREENER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_APPEALS_OFFICER,
    ROLE_GUARDIAN,
    ROLE_PROVIDER,
)

TEST_USERS = {
    "program_admin": build_user_headers(PROGRAM_ADMIN_USER_ID, ROLE_PROGRAM_ADMIN),
    "eligibility_officer": build_user_headers(
        ELIGIBILITY_OFFICER_USER_ID, ROLE_ELIGIBILITY_OFFICER
    ),
    "expense_reviewer": build_user_headers(
        EXPENSE_REVIEWER_USER_ID, ROLE_EXPENSE_REVIEWER
    ),
    "second_expense_reviewer": build_user_headers(
        SECOND_EXPENSE_REVIEWER_USER_ID, ROLE_EXPENSE_REVIEWER
    ),
    "compliance_officer": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, ROLE_COMPLIANCE_OFFICER
    ),
    "appeals_officer": build_user_headers(APPEALS_OFFICER_USER_ID, ROLE_APPEALS_OFFICER),
    "vendor_screener": build_user_headers(VENDOR_SCREENER_USER_ID, ROLE_VENDOR_SCREENER),
}

PA = TEST_USERS["program_admin"]
EO = TEST_USERS["eligibility_officer"]
ER1 = TEST_USERS["expense_reviewer"]
ER2 = TEST_USERS["second_expense_reviewer"]
CO = TEST_USERS["compliance_officer"]
AO = TEST_USERS["appeals_officer"]
VS = TEST_USERS["vendor_screener"]


def make_guardian_headers(student_id):
    """Headers for the guardian acting on behalf of ``student_id``."""
    return build_user_headers(str(student_id), ROLE_GUARDIAN)


def make_provider_headers(provider_id):
    """Headers for the provider acting as itself."""
    return build_user_headers(str(provider_id), ROLE_PROVIDER)


def make_appeals_officer_headers(user_id):
    """An appeals officer acting under an arbitrary operator identifier.

    Used to place the appeals officer's identity on top of the operator who
    authored the decision under appeal, which the segregation-of-duties rule
    must refuse.
    """
    return build_user_headers(str(user_id), ROLE_APPEALS_OFFICER)


def make_expense_reviewer_headers(user_id):
    """An expense reviewer acting under an arbitrary operator identifier."""
    return build_user_headers(str(user_id), ROLE_EXPENSE_REVIEWER)


def make_compliance_officer_headers(user_id):
    """A compliance officer acting under an arbitrary operator identifier."""
    return build_user_headers(str(user_id), ROLE_COMPLIANCE_OFFICER)


def headers_without_role(user_id):
    """Well-formed identity but no ``X-User-Role`` header at all."""
    return {"X-User-ID": str(user_id), "Content-Type": "application/json"}


def headers_without_user_id(role):
    """A declared role but no ``X-User-ID`` header at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def anonymous_headers():
    """Neither of the two mandatory identity headers."""
    return {"Content-Type": "application/json"}


def headers_with_unknown_role(user_id):
    """A syntactically present role that is not one of the eight recognised names."""
    return build_user_headers(str(user_id), "Superintendent")


__all__ = [
    "PROGRAM_ADMIN_USER_ID",
    "ELIGIBILITY_OFFICER_USER_ID",
    "EXPENSE_REVIEWER_USER_ID",
    "SECOND_EXPENSE_REVIEWER_USER_ID",
    "COMPLIANCE_OFFICER_USER_ID",
    "APPEALS_OFFICER_USER_ID",
    "VENDOR_SCREENER_USER_ID",
    "ROLE_PROGRAM_ADMIN",
    "ROLE_ELIGIBILITY_OFFICER",
    "ROLE_EXPENSE_REVIEWER",
    "ROLE_VENDOR_SCREENER",
    "ROLE_COMPLIANCE_OFFICER",
    "ROLE_APPEALS_OFFICER",
    "ROLE_GUARDIAN",
    "ROLE_PROVIDER",
    "ALL_ROLE_NAMES",
    "TEST_USERS",
    "PA",
    "EO",
    "ER1",
    "ER2",
    "CO",
    "AO",
    "VS",
    "make_guardian_headers",
    "make_provider_headers",
    "make_appeals_officer_headers",
    "make_expense_reviewer_headers",
    "make_compliance_officer_headers",
    "headers_without_role",
    "headers_without_user_id",
    "anonymous_headers",
    "headers_with_unknown_role",
]
