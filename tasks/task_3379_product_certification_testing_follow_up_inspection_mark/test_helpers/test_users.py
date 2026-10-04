"""Caller identities and header builders for the seven declared roles.

Five roles are opaque (PRD 2.1): their ``X-User-ID`` is never compared to a
stored entity, so a stable identifier works and the shared constants in
``TEST_USERS`` are their canonical form.

Two roles are entity-backed: ``ManufacturerRep`` must present the ``id`` of a
real ``Manufacturer`` and ``AHJAuthority`` the ``id`` of a real
``Jurisdiction`` - anything else is rejected ``ERR_UNAUTHENTICATED``, and
ownership checks then compare that id against the resource. For those roles
the per-instance builders (``make_manufacturer_rep_headers``,
``make_ahj_authority_headers``) are the only correct form whenever a call is
authenticated or ownership-gated. The shared ``TEST_USERS`` entries for these
two roles exist only as a fallback for tests whose outcome cannot depend on
the caller resolving to a real entity; passing them to any authenticated
endpoint will fail with 401.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_AHJ_AUTHORITY,
    ROLE_CERTIFICATION_BODY_ADMIN,
    ROLE_CERTIFICATION_REVIEWER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_FACTORY_INSPECTOR,
    ROLE_MANUFACTURER_REP,
    ROLE_TEST_ENGINEER,
)

__all__ = [
    "DEFAULT_ADMIN_ID",
    "DEFAULT_ENGINEER_ID",
    "SECOND_ENGINEER_ID",
    "DEFAULT_REVIEWER_ID",
    "SECOND_REVIEWER_ID",
    "DEFAULT_INSPECTOR_ID",
    "DEFAULT_COMPLIANCE_OFFICER_ID",
    "UNDECLARED_ROLE",
    "TEST_USERS",
    "make_certification_body_admin_headers",
    "make_manufacturer_rep_headers",
    "make_test_engineer_headers",
    "make_certification_reviewer_headers",
    "make_factory_inspector_headers",
    "make_compliance_officer_headers",
    "make_ahj_authority_headers",
    "no_auth_headers",
    "headers_without_user_id",
    "headers_without_role",
    "headers_with_undeclared_role",
]

# Stable opaque identifiers for the five opaque roles. Two engineers and two
# reviewers exist so segregation-of-duties scenarios can separate the person
# who recorded results from the person who decides.
DEFAULT_ADMIN_ID = "admin-1"
DEFAULT_ENGINEER_ID = "eng-1"
SECOND_ENGINEER_ID = "eng-2"
DEFAULT_REVIEWER_ID = "rev-1"
SECOND_REVIEWER_ID = "rev-2"
DEFAULT_INSPECTOR_ID = "insp-1"
DEFAULT_COMPLIANCE_OFFICER_ID = "co-1"

# A role name the API does not declare (for ERR_UNAUTHENTICATED coverage).
UNDECLARED_ROLE = "SuperUser"

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles: canonical header sets.
    "certification_body_admin_headers": build_user_headers(
        DEFAULT_ADMIN_ID, ROLE_CERTIFICATION_BODY_ADMIN
    ),
    "test_engineer_headers": build_user_headers(DEFAULT_ENGINEER_ID, ROLE_TEST_ENGINEER),
    "certification_reviewer_headers": build_user_headers(
        DEFAULT_REVIEWER_ID, ROLE_CERTIFICATION_REVIEWER
    ),
    "factory_inspector_headers": build_user_headers(DEFAULT_INSPECTOR_ID, ROLE_FACTORY_INSPECTOR),
    "compliance_officer_headers": build_user_headers(
        DEFAULT_COMPLIANCE_OFFICER_ID, ROLE_COMPLIANCE_OFFICER
    ),
    # Entity-backed roles: FALLBACK ONLY - these placeholder ids resolve to no
    # real entity, so any authenticated endpoint rejects them with 401. Use
    # make_manufacturer_rep_headers(manufacturer["id"]) /
    # make_ahj_authority_headers(jurisdiction["id"]) instead.
    "manufacturer_rep_headers": build_user_headers(
        "manufacturer-rep-placeholder", ROLE_MANUFACTURER_REP
    ),
    "ahj_authority_headers": build_user_headers("ahj-placeholder", ROLE_AHJ_AUTHORITY),
}


# ── Per-instance builders ──────────────────────────────────────────────────

def make_certification_body_admin_headers(user_id: str = DEFAULT_ADMIN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CERTIFICATION_BODY_ADMIN)


def make_manufacturer_rep_headers(manufacturer_id: str) -> Dict[str, str]:
    """Headers for a ManufacturerRep. ``manufacturer_id`` MUST be the id of an
    existing Manufacturer - the role is entity-backed, so any other value is
    rejected ERR_UNAUTHENTICATED, and ownership checks compare it to each
    resource's manufacturer_id."""
    return build_user_headers(manufacturer_id, ROLE_MANUFACTURER_REP)


def make_test_engineer_headers(user_id: str = DEFAULT_ENGINEER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_TEST_ENGINEER)


def make_certification_reviewer_headers(user_id: str = DEFAULT_REVIEWER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CERTIFICATION_REVIEWER)


def make_factory_inspector_headers(user_id: str = DEFAULT_INSPECTOR_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_FACTORY_INSPECTOR)


def make_compliance_officer_headers(user_id: str = DEFAULT_COMPLIANCE_OFFICER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_ahj_authority_headers(jurisdiction_id: str) -> Dict[str, str]:
    """Headers for an AHJAuthority. ``jurisdiction_id`` MUST be the id of an
    existing Jurisdiction, and acceptance decisions additionally require it to
    equal the field evaluation's site_jurisdiction_id."""
    return build_user_headers(jurisdiction_id, ROLE_AHJ_AUTHORITY)


# ── Malformed-credential header sets (authentication negative tests) ───────

def no_auth_headers() -> Dict[str, str]:
    """No X-User-ID and no X-User-Role at all."""
    return {"Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_CERTIFICATION_BODY_ADMIN) -> Dict[str, str]:
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = DEFAULT_ADMIN_ID) -> Dict[str, str]:
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_undeclared_role(
    user_id: str = DEFAULT_ADMIN_ID, role: Optional[str] = None
) -> Dict[str, str]:
    return build_user_headers(user_id, role or UNDECLARED_ROLE)
