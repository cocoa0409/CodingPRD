"""Caller identities and header builders.

Identity binding differs by role (PRD 2.1):

* ``FieldInspector`` and ``Applicator`` -- ``X-User-ID`` is the ``id`` of the
  acting ``Inspector`` row, so headers must be built per persisted inspector.
* ``PropertyOwner`` -- ``X-User-ID`` is the ``id`` of the acting ``Property``.
* ``ComplianceOfficer``, ``BranchManager`` and ``ClaimsAdjudicator`` --
  ``X-User-ID`` is an opaque operator identifier tied to no entity, so a
  shared constant is appropriate.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_APPLICATOR,
    ROLE_BRANCH_MANAGER,
    ROLE_CLAIMS_ADJUDICATOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_FIELD_INSPECTOR,
    ROLE_PROPERTY_OWNER,
)

# Opaque operator identifiers -- never compared against any entity id.
COMPLIANCE_OFFICER_ID = "officer-1"
BRANCH_MANAGER_ID = "mgr-1"
BRANCH_MANAGER_ID_ALT = "mgr-2"
CLAIMS_ADJUDICATOR_ID = "adj-1"
CLAIMS_ADJUDICATOR_ID_ALT = "adj-2"

TEST_USERS = {
    ROLE_COMPLIANCE_OFFICER: build_user_headers(
        COMPLIANCE_OFFICER_ID, ROLE_COMPLIANCE_OFFICER
    ),
    ROLE_BRANCH_MANAGER: build_user_headers(BRANCH_MANAGER_ID, ROLE_BRANCH_MANAGER),
    ROLE_CLAIMS_ADJUDICATOR: build_user_headers(
        CLAIMS_ADJUDICATOR_ID, ROLE_CLAIMS_ADJUDICATOR
    ),
}

OFFICER_HEADERS = TEST_USERS[ROLE_COMPLIANCE_OFFICER]
MANAGER_HEADERS = TEST_USERS[ROLE_BRANCH_MANAGER]
ADJUDICATOR_HEADERS = TEST_USERS[ROLE_CLAIMS_ADJUDICATOR]


def make_compliance_officer_headers(user_id=COMPLIANCE_OFFICER_ID):
    """Headers for a compliance operator; the id is opaque."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_branch_manager_headers(user_id=BRANCH_MANAGER_ID):
    """Headers for an underwriting operator; the id is opaque."""
    return build_user_headers(user_id, ROLE_BRANCH_MANAGER)


def make_claims_adjudicator_headers(user_id=CLAIMS_ADJUDICATOR_ID):
    """Headers for an adjudicating operator; the id is opaque."""
    return build_user_headers(user_id, ROLE_CLAIMS_ADJUDICATOR)


def make_field_inspector_headers(inspector_id):
    """Headers for a field inspector; the id is the acting Inspector's id."""
    return build_user_headers(inspector_id, ROLE_FIELD_INSPECTOR)


def make_applicator_headers(inspector_id):
    """Headers for an applicator; the id is the acting Inspector's id."""
    return build_user_headers(inspector_id, ROLE_APPLICATOR)


def make_property_owner_headers(property_id):
    """Headers for a homeowner; the id is the acting Property's id."""
    return build_user_headers(property_id, ROLE_PROPERTY_OWNER)


def make_unknown_role_headers(user_id="who-1", role="Auditor"):
    """Headers naming a role outside the six declared ones."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role=ROLE_COMPLIANCE_OFFICER):
    """Headers whose X-User-ID is empty -- an empty header, never whitespace."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id=COMPLIANCE_OFFICER_ID):
    """Headers whose X-User-Role is empty -- an empty header, never whitespace."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_missing_user_id(role=ROLE_COMPLIANCE_OFFICER):
    """Headers with the X-User-ID header genuinely omitted."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id=COMPLIANCE_OFFICER_ID):
    """Headers with the X-User-Role header genuinely omitted."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


NO_HEADERS = {"Content-Type": "application/json"}
