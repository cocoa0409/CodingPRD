"""Auth header builders for the six declared roles of the awareness program API.

Two of the six roles are entity backed: the `X-User-ID` a `Manager` or a
`Learner` presents must be the id of an actual `Employee` row, because the
per-row ownership checks read `CurriculumAssignment.employee_id` and
`Employee.manager_id`.  Use :func:`make_learner_headers` and
:func:`make_manager_headers` for those, never the shared constants below.

The remaining four roles carry opaque identifiers.  Campaign authorship and
segregation of duties are keyed on the opaque `X-User-ID`, so the author and
approver identities are pinned to stable literals here.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CAMPAIGN_APPROVER,
    ROLE_CAMPAIGN_AUTHOR,
    ROLE_LEARNER,
    ROLE_MANAGER,
    ROLE_PROGRAM_ADMIN,
    ROLE_SECURITY_ANALYST,
)

PROGRAM_ADMIN_ID = "program-admin-1"
AUTHOR_1_ID = "author-1"
AUTHOR_2_ID = "author-2"
APPROVER_1_ID = "approver-1"
APPROVER_2_ID = "approver-2"
SECURITY_ANALYST_ID = "analyst-1"

TEST_USERS = {
    "program_admin_headers": build_user_headers(PROGRAM_ADMIN_ID, ROLE_PROGRAM_ADMIN),
    "campaign_author_headers": build_user_headers(AUTHOR_1_ID, ROLE_CAMPAIGN_AUTHOR),
    "campaign_author_2_headers": build_user_headers(AUTHOR_2_ID, ROLE_CAMPAIGN_AUTHOR),
    "campaign_approver_headers": build_user_headers(APPROVER_1_ID, ROLE_CAMPAIGN_APPROVER),
    "campaign_approver_2_headers": build_user_headers(APPROVER_2_ID, ROLE_CAMPAIGN_APPROVER),
    "security_analyst_headers": build_user_headers(SECURITY_ANALYST_ID, ROLE_SECURITY_ANALYST),
}

ADMIN = TEST_USERS["program_admin_headers"]
AUTHOR = TEST_USERS["campaign_author_headers"]
AUTHOR_2 = TEST_USERS["campaign_author_2_headers"]
APPROVER = TEST_USERS["campaign_approver_headers"]
APPROVER_2 = TEST_USERS["campaign_approver_2_headers"]
ANALYST = TEST_USERS["security_analyst_headers"]


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_ID) -> dict:
    """Headers for the ProgramAdmin role (opaque identifier)."""
    return build_user_headers(user_id, ROLE_PROGRAM_ADMIN)


def make_campaign_author_headers(user_id: str = AUTHOR_1_ID) -> dict:
    """Headers for a CampaignAuthor; the id becomes the campaign's author_user_id."""
    return build_user_headers(user_id, ROLE_CAMPAIGN_AUTHOR)


def make_campaign_approver_headers(user_id: str = APPROVER_1_ID) -> dict:
    """Headers for a CampaignApprover; the id becomes the campaign's reviewer_user_id."""
    return build_user_headers(user_id, ROLE_CAMPAIGN_APPROVER)


def make_security_analyst_headers(user_id: str = SECURITY_ANALYST_ID) -> dict:
    """Headers for the SecurityAnalyst role (opaque identifier)."""
    return build_user_headers(user_id, ROLE_SECURITY_ANALYST)


def make_manager_headers(employee_id: str) -> dict:
    """Headers for a Manager: `employee_id` must be the manager's own Employee id."""
    return build_user_headers(employee_id, ROLE_MANAGER)


def make_learner_headers(employee_id: str) -> dict:
    """Headers for a Learner: `employee_id` must be the learner's own Employee id."""
    return build_user_headers(employee_id, ROLE_LEARNER)


def make_headers(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role/id pair, including undeclared role values."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = PROGRAM_ADMIN_ID) -> dict:
    """Headers that omit `X-User-Role` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_PROGRAM_ADMIN) -> dict:
    """Headers that omit `X-User-ID` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = ROLE_PROGRAM_ADMIN) -> dict:
    """Headers whose `X-User-ID` is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}
