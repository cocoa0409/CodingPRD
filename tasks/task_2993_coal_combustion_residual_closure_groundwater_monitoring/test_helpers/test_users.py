"""Caller identities and the header pairs that declare them.

The contract splits the seven roles in two. Four are **opaque**: their
``X-User-ID`` is an operator string the server never resolves, so a fixed
identifier per role is enough and each role gets its own distinct value.
Three are **entity-backed**: their ``X-User-ID`` must be the ``id`` of a
registered ``QualifiedProfessional``, so headers for those roles are built
per-instance from an identifier the roster minted.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_HYDROGEOLOGIST,
    ROLE_PROFESSIONAL_ENGINEER,
    ROLE_PUBLIC_VIEWER,
    ROLE_REGULATOR,
    ROLE_STATISTICAL_REVIEWER,
    ROLE_UTILITY_ADMIN,
    UNDECLARED_ROLE,
)

# ── Opaque operator identities ────────────────────────────────────────────

TEST_USERS: Dict[str, Dict[str, str]] = {
    "utility_admin": {
        "user_id": "11111111-1111-4111-8111-111111111111",
        "role": ROLE_UTILITY_ADMIN,
    },
    "second_utility_admin": {
        "user_id": "11111111-1111-4111-8111-111111111112",
        "role": ROLE_UTILITY_ADMIN,
    },
    "compliance_officer": {
        "user_id": "22222222-2222-4222-8222-222222222222",
        "role": ROLE_COMPLIANCE_OFFICER,
    },
    "second_compliance_officer": {
        "user_id": "22222222-2222-4222-8222-222222222223",
        "role": ROLE_COMPLIANCE_OFFICER,
    },
    "regulator": {
        "user_id": "33333333-3333-4333-8333-333333333333",
        "role": ROLE_REGULATOR,
    },
    "public_viewer": {
        "user_id": "44444444-4444-4444-8444-444444444444",
        "role": ROLE_PUBLIC_VIEWER,
    },
}

UTILITY_ADMIN_HEADERS = build_user_headers(
    TEST_USERS["utility_admin"]["user_id"], TEST_USERS["utility_admin"]["role"]
)
SECOND_UTILITY_ADMIN_HEADERS = build_user_headers(
    TEST_USERS["second_utility_admin"]["user_id"], TEST_USERS["second_utility_admin"]["role"]
)
COMPLIANCE_OFFICER_HEADERS = build_user_headers(
    TEST_USERS["compliance_officer"]["user_id"], TEST_USERS["compliance_officer"]["role"]
)
SECOND_COMPLIANCE_OFFICER_HEADERS = build_user_headers(
    TEST_USERS["second_compliance_officer"]["user_id"],
    TEST_USERS["second_compliance_officer"]["role"],
)
REGULATOR_HEADERS = build_user_headers(
    TEST_USERS["regulator"]["user_id"], TEST_USERS["regulator"]["role"]
)
PUBLIC_VIEWER_HEADERS = build_user_headers(
    TEST_USERS["public_viewer"]["user_id"], TEST_USERS["public_viewer"]["role"]
)


# ── Entity-backed professional identities ─────────────────────────────────


def make_engineer_headers(professional_id: str) -> Dict[str, str]:
    """Act as a ``ProfessionalEngineer`` backed by this roster record."""
    return build_user_headers(professional_id, ROLE_PROFESSIONAL_ENGINEER)


def make_hydrogeologist_headers(professional_id: str) -> Dict[str, str]:
    """Act as a ``Hydrogeologist`` backed by this roster record."""
    return build_user_headers(professional_id, ROLE_HYDROGEOLOGIST)


def make_statistical_reviewer_headers(professional_id: str) -> Dict[str, str]:
    """Act as a ``StatisticalReviewer`` backed by this roster record."""
    return build_user_headers(professional_id, ROLE_STATISTICAL_REVIEWER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Build an arbitrary identity pair."""
    return build_user_headers(user_id, role)


# ── Malformed credentials ─────────────────────────────────────────────────


def headers_with_empty_role(user_id: str) -> Dict[str, str]:
    """A present-but-empty role header, which the contract treats as absent.

    The value is the empty string exactly - never whitespace, which would be a
    non-empty header value and would test a different rule.
    """
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """A present-but-empty identity header."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """An identity header with no role header at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """A role header with no identity header at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_undeclared_role(user_id: str) -> Dict[str, str]:
    """A well formed role name that is not one of the contract's seven."""
    return build_user_headers(user_id, UNDECLARED_ROLE)
