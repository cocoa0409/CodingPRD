"""Identity headers for the seven roles of section 2.1.

Three roles carry an opaque operator identifier that the server never
compares to any row: ``SchemeManager``, ``AssessmentManager`` and
``ComplaintOfficer``. Those three get ready-made header dictionaries.

Four roles are entity-backed and their ``X-User-ID`` must resolve to a real
row, so they are only reachable through a builder that takes that row's id:
``LeadAssessor``, ``TechnicalExpert`` and ``DecisionPanelMember`` carry an
``Assessor`` id, and ``ApplicantContact`` carries an
``ApplicantOrganization`` id. There is deliberately no module-level constant
for those four -- sharing one id across identities the PRD requires to be
distinct is exactly the mistake this module exists to prevent.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_APPLICANT_CONTACT,
    ROLE_ASSESSMENT_MANAGER,
    ROLE_COMPLAINT_OFFICER,
    ROLE_DECISION_PANEL_MEMBER,
    ROLE_LEAD_ASSESSOR,
    ROLE_SCHEME_MANAGER,
    ROLE_TECHNICAL_EXPERT,
)

# --- Opaque operator identifiers -----------------------------------------

SCHEME_MANAGER_USER_ID = "op-scheme-manager-01"
ASSESSMENT_MANAGER_USER_ID = "op-assessment-manager-01"
COMPLAINT_OFFICER_USER_ID = "op-complaint-officer-01"

SCHEME_MANAGER = build_user_headers(SCHEME_MANAGER_USER_ID, ROLE_SCHEME_MANAGER)
ASSESSMENT_MANAGER = build_user_headers(
    ASSESSMENT_MANAGER_USER_ID, ROLE_ASSESSMENT_MANAGER
)
COMPLAINT_OFFICER = build_user_headers(
    COMPLAINT_OFFICER_USER_ID, ROLE_COMPLAINT_OFFICER
)

TEST_USERS = {
    ROLE_SCHEME_MANAGER: SCHEME_MANAGER,
    ROLE_ASSESSMENT_MANAGER: ASSESSMENT_MANAGER,
    ROLE_COMPLAINT_OFFICER: COMPLAINT_OFFICER,
}


# --- Entity-backed identities -------------------------------------------


def make_lead_assessor_headers(assessor_id: str) -> Dict[str, str]:
    """Act as the ``LeadAssessor`` whose ``Assessor`` id is ``assessor_id``."""
    return build_user_headers(assessor_id, ROLE_LEAD_ASSESSOR)


def make_technical_expert_headers(assessor_id: str) -> Dict[str, str]:
    """Act as the ``TechnicalExpert`` whose ``Assessor`` id is ``assessor_id``."""
    return build_user_headers(assessor_id, ROLE_TECHNICAL_EXPERT)


def make_decision_panel_member_headers(assessor_id: str) -> Dict[str, str]:
    """Act as the ``DecisionPanelMember`` with that ``Assessor`` id."""
    return build_user_headers(assessor_id, ROLE_DECISION_PANEL_MEMBER)


def make_applicant_contact_headers(organization_id: str) -> Dict[str, str]:
    """Act as the ``ApplicantContact`` of that ``ApplicantOrganization``."""
    return build_user_headers(organization_id, ROLE_APPLICANT_CONTACT)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Act as an arbitrary role/identifier pair, for role-matrix tests."""
    return build_user_headers(user_id, role)


# --- Deliberately malformed identity headers ----------------------------
#
# An empty header value is sent as the empty string. A whitespace-only value
# is never used: the HTTP client rejects it locally and the request would
# never reach the server, so it could not exercise ERR_UNAUTHENTICATED.


def headers_with_empty_role(user_id: str) -> Dict[str, str]:
    """A well-formed identifier with an empty ``X-User-Role`` value."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """A valid role with an empty ``X-User-ID`` value."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_without_role(user_id: str) -> Dict[str, str]:
    """``X-User-Role`` absent altogether."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """``X-User-ID`` absent altogether."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
