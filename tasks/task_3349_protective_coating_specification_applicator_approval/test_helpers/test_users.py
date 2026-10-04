"""Caller identities for the seven declared roles (PRD §2.1).

Six roles are opaque: their ``X-User-ID`` is never compared to a stored row,
so a stable identifier is enough. ``ApplicatorRep`` is entity-backed: the
header's ``X-User-ID`` must equal the ``id`` of the ``Applicator`` the rep
belongs to, because ownership checks on applicator-referencing resources
compare the foreign key to ``X-User-ID``. That role therefore has a per-call
builder; every fixture that acts as the applicator must use it.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_APPLICATOR_REP,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_INSPECTOR,
    ROLE_OWNER_REPRESENTATIVE,
    ROLE_PLATFORM_ADMIN,
    ROLE_PROJECT_ENGINEER,
    ROLE_TECHNICAL_SERVICE_ENGINEER,
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": {"id": "ops-admin-000001", "role": ROLE_PLATFORM_ADMIN},
    "technical_service_engineer": {"id": "tse-000001", "role": ROLE_TECHNICAL_SERVICE_ENGINEER},
    "project_engineer": {"id": "pe-000001", "role": ROLE_PROJECT_ENGINEER},
    "owner_representative": {"id": "owner-000001", "role": ROLE_OWNER_REPRESENTATIVE},
    "inspector": {"id": "inspector-000001", "role": ROLE_INSPECTOR},
    "compliance_officer": {"id": "compliance-000001", "role": ROLE_COMPLIANCE_OFFICER},
}

PLATFORM_ADMIN_HEADERS = build_user_headers(
    TEST_USERS["platform_admin"]["id"], ROLE_PLATFORM_ADMIN
)
TECHNICAL_SERVICE_ENGINEER_HEADERS = build_user_headers(
    TEST_USERS["technical_service_engineer"]["id"], ROLE_TECHNICAL_SERVICE_ENGINEER
)
PROJECT_ENGINEER_HEADERS = build_user_headers(
    TEST_USERS["project_engineer"]["id"], ROLE_PROJECT_ENGINEER
)
OWNER_REPRESENTATIVE_HEADERS = build_user_headers(
    TEST_USERS["owner_representative"]["id"], ROLE_OWNER_REPRESENTATIVE
)
INSPECTOR_HEADERS = build_user_headers(
    TEST_USERS["inspector"]["id"], ROLE_INSPECTOR
)
COMPLIANCE_OFFICER_HEADERS = build_user_headers(
    TEST_USERS["compliance_officer"]["id"], ROLE_COMPLIANCE_OFFICER
)


# ── Entity-backed role ───────────────────────────────────────────────────────

def make_applicator_rep_headers(applicator_id: str) -> Dict[str, str]:
    """Headers for the representative of the applicator with this identifier.

    Required on every applicator-side call (enrollment, begin-prep-inspection,
    coating application, mark-cured): the applicator's ``id`` is the identity.
    """
    return build_user_headers(applicator_id, ROLE_APPLICATOR_REP)


def make_inspector_headers(inspector_id: str) -> Dict[str, str]:
    """Headers for an Inspector with a specific opaque identity."""
    return build_user_headers(inspector_id, ROLE_INSPECTOR)


# ── Malformed credentials, for the header-presence tier ─────────────────────

def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
