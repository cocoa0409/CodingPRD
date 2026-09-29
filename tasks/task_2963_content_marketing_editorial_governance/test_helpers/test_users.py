"""
Pre-built auth headers for every role.

Identity semantics differ between the roles (PRD 2.1): a
``SubjectMatterExpertUser`` must present the ``id`` of the acting
``SubjectMatterExpert`` row in ``X-User-ID``, so those headers can only be
built once the expert exists — use :func:`expert_headers`. The five opaque
roles get fixed operator identifiers here, and the two managing-editor
identities are deliberately distinct so that publication segregation of
duties can be exercised without borrowing a reviewer's identity.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ACCESSIBILITY_REVIEWER,
    ROLE_ANALYTICS_SERVICE,
    ROLE_BRAND_REVIEWER,
    ROLE_LEGAL_REVIEWER,
    ROLE_MANAGING_EDITOR,
    ROLE_SME_USER,
    UNDECLARED_ROLE,
)

# ─── Opaque operator identifiers ──────────────────────

EDITOR_ONE_ID = "me-1"
EDITOR_TWO_ID = "me-2"
EDITOR_THREE_ID = "me-3"
LEGAL_ONE_ID = "legal-1"
LEGAL_TWO_ID = "legal-2"
LEGAL_THREE_ID = "legal-3"
LEGAL_REVIEWER_ID = "lr-1"
BRAND_ONE_ID = "brand-1"
ACCESSIBILITY_ONE_ID = "a11y-1"
ANALYTICS_ONE_ID = "analytics-1"
UNDECLARED_ROLE_USER_ID = "cc-1"

# ─── Header dictionaries ──────────────────────────────

MANAGING_EDITOR = build_user_headers(EDITOR_ONE_ID, ROLE_MANAGING_EDITOR)
MANAGING_EDITOR_TWO = build_user_headers(EDITOR_TWO_ID, ROLE_MANAGING_EDITOR)
MANAGING_EDITOR_THREE = build_user_headers(EDITOR_THREE_ID, ROLE_MANAGING_EDITOR)

LEGAL_REVIEWER = build_user_headers(LEGAL_REVIEWER_ID, ROLE_LEGAL_REVIEWER)
LEGAL_REVIEWER_ONE = build_user_headers(LEGAL_ONE_ID, ROLE_LEGAL_REVIEWER)
LEGAL_REVIEWER_TWO = build_user_headers(LEGAL_TWO_ID, ROLE_LEGAL_REVIEWER)
LEGAL_REVIEWER_THREE = build_user_headers(LEGAL_THREE_ID, ROLE_LEGAL_REVIEWER)

BRAND_REVIEWER = build_user_headers(BRAND_ONE_ID, ROLE_BRAND_REVIEWER)
ACCESSIBILITY_REVIEWER = build_user_headers(
    ACCESSIBILITY_ONE_ID, ROLE_ACCESSIBILITY_REVIEWER
)
ANALYTICS_SERVICE = build_user_headers(ANALYTICS_ONE_ID, ROLE_ANALYTICS_SERVICE)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "managing_editor": MANAGING_EDITOR,
    "managing_editor_two": MANAGING_EDITOR_TWO,
    "managing_editor_three": MANAGING_EDITOR_THREE,
    "legal_reviewer": LEGAL_REVIEWER,
    "legal_reviewer_one": LEGAL_REVIEWER_ONE,
    "legal_reviewer_two": LEGAL_REVIEWER_TWO,
    "legal_reviewer_three": LEGAL_REVIEWER_THREE,
    "brand_reviewer": BRAND_REVIEWER,
    "accessibility_reviewer": ACCESSIBILITY_REVIEWER,
    "analytics_service": ANALYTICS_SERVICE,
}

# Every role other than ManagingEditor, for exclusive-write denial probes.
NON_EDITOR_ROLE_HEADERS = [
    LEGAL_REVIEWER,
    BRAND_REVIEWER,
    ACCESSIBILITY_REVIEWER,
    ANALYTICS_SERVICE,
]


def expert_headers(expert_id: str) -> Dict[str, str]:
    """
    Build ``SubjectMatterExpertUser`` headers for a persisted expert row.

    ``X-User-ID`` is the expert's own ``id`` because ownership checks compare
    a brief's ``sme_expert_id`` directly against it (PRD 2.1).
    """
    return build_user_headers(expert_id, ROLE_SME_USER)


# Backwards-compatible alias with a fully spelled-out name.
make_subject_matter_expert_headers = expert_headers


def undeclared_role_headers() -> Dict[str, str]:
    """Headers naming a role string outside the six declared roles (PRD 2.1)."""
    return build_user_headers(UNDECLARED_ROLE_USER_ID, UNDECLARED_ROLE)


def blank_auth_headers() -> Dict[str, str]:
    """
    Headers whose two auth values are present but zero-length.

    The PRD treats an empty ``X-User-ID`` or ``X-User-Role`` as unauthenticated.
    The values must be genuinely empty strings rather than whitespace, because a
    whitespace value is a different (non-empty) input.
    """
    return {"X-User-ID": "", "X-User-Role": "", "Content-Type": "application/json"}


def missing_auth_headers() -> Dict[str, str]:
    """Headers with neither auth header present at all (PRD 2.1)."""
    return {"Content-Type": "application/json"}


def headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Build headers for an arbitrary role/user pair."""
    return build_user_headers(user_id, role)
