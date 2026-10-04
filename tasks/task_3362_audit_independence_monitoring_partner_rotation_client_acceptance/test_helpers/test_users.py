"""Caller identities for the six declared roles.

Every request carries an ``X-User-ID`` and an ``X-User-Role`` header. Four
roles are opaque: their identifier is not tied to any persisted row, so a
stable constant is the canonical form. Two roles are entity-backed — an
``EngagementPartner`` and a ``QualityReviewer`` act as a stored Professional,
so every call that touches a resource referencing a Professional must present
that professional's identifier. Those two therefore get per-instance builders
that take the identifier the test created; the shared constant is only a
fallback for calls whose success does not depend on ownership.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ── Shared constants ───────────────────────────────────────────────────────
# Opaque operators: the identifier is recorded but never compared to a row.
PLATFORM_ADMIN_HEADERS: Dict[str, str] = build_user_headers("ops-admin-1", UserRole.PLATFORM_ADMIN)
COMMITTEE_HEADERS: Dict[str, str] = build_user_headers(
    "committee-rao-1", UserRole.CLIENT_ACCEPTANCE_COMMITTEE
)
OFFICER_HEADERS: Dict[str, str] = build_user_headers(
    "independence-office-1", UserRole.INDEPENDENCE_OFFICER
)
LIAISON_HEADERS: Dict[str, str] = build_user_headers(
    "audit-committee-liaison-1", UserRole.AUDIT_COMMITTEE_LIAISON
)

# Entity-backed roles: the shared constants name no real Professional row and
# are safe only for calls that are not ownership-gated.
ENGAGEMENT_PARTNER_HEADERS: Dict[str, str] = build_user_headers(
    "ep-hollis", UserRole.ENGAGEMENT_PARTNER
)
QUALITY_REVIEWER_HEADERS: Dict[str, str] = build_user_headers(
    "qr-standby", UserRole.QUALITY_REVIEWER
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin_headers": PLATFORM_ADMIN_HEADERS,
    "committee_headers": COMMITTEE_HEADERS,
    "officer_headers": OFFICER_HEADERS,
    "liaison_headers": LIAISON_HEADERS,
    "engagement_partner_headers": ENGAGEMENT_PARTNER_HEADERS,
    "quality_reviewer_headers": QUALITY_REVIEWER_HEADERS,
}


# ── Per-instance builders (mandatory for the entity-backed roles) ──────────

def make_engagement_partner_headers(professional_id: str) -> Dict[str, str]:
    """Headers for an EngagementPartner acting as this Professional."""
    return build_user_headers(professional_id, UserRole.ENGAGEMENT_PARTNER)


def make_quality_reviewer_headers(professional_id: str) -> Dict[str, str]:
    """Headers for a QualityReviewer acting as this Professional."""
    return build_user_headers(professional_id, UserRole.QUALITY_REVIEWER)


# ── Malformed credentials, for the header-presence tier ────────────────────

def headers_without_auth() -> Dict[str, str]:
    """No authentication headers at all."""
    return {"Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """``X-User-Role`` present, ``X-User-ID`` omitted."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """``X-User-ID`` present, ``X-User-Role`` omitted."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
