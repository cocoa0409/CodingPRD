"""Caller identities for the five roles the PRD declares.

Four roles are opaque operator identities — the server never compares their
``X-User-ID`` to any entity's id — so a stable identifier is enough and the
shared constants below are their canonical form.

``JurisdictionRegistrar`` is entity-backed: its ``X-User-ID`` must equal the
``id`` of the ``Jurisdiction`` it acts for, and ownership checks compare
resource jurisdiction foreign keys against it. Use
``make_jurisdiction_registrar_headers(jurisdiction["id"])`` for every
registrar call that touches jurisdiction-scoped resources. The shared
``TEST_USERS["jurisdiction_registrar_headers"]`` constant is a fallback only
for tests that never exercise ownership or existence of the registrar's own
jurisdiction (for example a pure role-authorization probe).

``EMPTY_HEADERS`` and the two ``headers_without_*`` builders support the
header-presence rung of the validation ladder.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque identifiers for the non-entity-backed roles.
ASSOCIATION_ADMIN_ID = "a0000000-0000-4000-8000-0000000000a1"
CERTIFICATION_ENGINEER_ID = "a0000000-0000-4000-8000-0000000000a2"
FEDERAL_VERIFIER_ID = "a0000000-0000-4000-8000-0000000000a3"
AUDIT_AUTHORITY_ID = "a0000000-0000-4000-8000-0000000000a4"
# Fallback registrar identity: never equals a real jurisdiction's id, so it is
# only safe where no ownership or registrar-existence check is exercised.
PLACEHOLDER_REGISTRAR_ID = "a0000000-0000-4000-8000-0000000000a5"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "association_admin_headers": build_user_headers(
        ASSOCIATION_ADMIN_ID, UserRole.ASSOCIATION_ADMIN.value
    ),
    "jurisdiction_registrar_headers": build_user_headers(
        PLACEHOLDER_REGISTRAR_ID, UserRole.JURISDICTION_REGISTRAR.value
    ),
    "certification_engineer_headers": build_user_headers(
        CERTIFICATION_ENGINEER_ID, UserRole.CERTIFICATION_ENGINEER.value
    ),
    "federal_verifier_headers": build_user_headers(
        FEDERAL_VERIFIER_ID, UserRole.FEDERAL_VERIFIER.value
    ),
    "audit_authority_headers": build_user_headers(
        AUDIT_AUTHORITY_ID, UserRole.AUDIT_AUTHORITY.value
    ),
}

# Ready-made header dicts for the opaque roles (same objects as TEST_USERS).
ASSOCIATION_ADMIN_HEADERS = TEST_USERS["association_admin_headers"]
CERTIFICATION_ENGINEER_HEADERS = TEST_USERS["certification_engineer_headers"]
FEDERAL_VERIFIER_HEADERS = TEST_USERS["federal_verifier_headers"]
AUDIT_AUTHORITY_HEADERS = TEST_USERS["audit_authority_headers"]

# A request carrying no identity headers at all (the header-presence rung).
EMPTY_HEADERS: Dict[str, str] = {}


def make_jurisdiction_registrar_headers(jurisdiction_id: str) -> Dict[str, str]:
    """Headers for the registrar of a specific jurisdiction. Pass the real
    Jurisdiction ``id`` whenever the call is ownership-gated or presumes the
    registrar's jurisdiction exists — i.e. essentially every registrar call."""
    return build_user_headers(jurisdiction_id, UserRole.JURISDICTION_REGISTRAR.value)


def headers_without_user_id(role: str = UserRole.ASSOCIATION_ADMIN.value) -> Dict[str, str]:
    """Headers carrying only ``X-User-Role`` (missing ``X-User-ID``)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = ASSOCIATION_ADMIN_ID) -> Dict[str, str]:
    """Headers carrying only ``X-User-ID`` (missing ``X-User-Role``)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
