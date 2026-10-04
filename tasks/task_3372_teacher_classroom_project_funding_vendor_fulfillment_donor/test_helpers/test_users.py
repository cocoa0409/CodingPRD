"""Caller identities for the six declared roles.

Every request carries an ``X-User-ID`` and an ``X-User-Role`` header. Three
roles are entity-backed: a Teacher, a Donor and a Vendor must present the
identifier of the persisted row they act as, so those roles get per-call
builders that take the identifier the test created. Anonymous, Reviewer and
PlatformAdmin are opaque: the server never compares their identifier to a
stored row, so stable canned identifiers are enough.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import REVIEWER_SCREENER, REVIEWER_VETTER
from .types import UserRole

# Opaque identifiers for the roles never matched against a stored row.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": {"id": "admin-1", "role": UserRole.PLATFORM_ADMIN.value},
    "anonymous": {"id": "anon-registrant-1", "role": UserRole.ANONYMOUS.value},
    "reviewer_screener": {"id": REVIEWER_SCREENER, "role": UserRole.REVIEWER.value},
    "reviewer_vetter": {"id": REVIEWER_VETTER, "role": UserRole.REVIEWER.value},
}

ADMIN_HEADERS = build_user_headers(
    TEST_USERS["platform_admin"]["id"], TEST_USERS["platform_admin"]["role"]
)
ANON_HEADERS = build_user_headers(
    TEST_USERS["anonymous"]["id"], TEST_USERS["anonymous"]["role"]
)
REVIEWER_ANA_HEADERS = build_user_headers(REVIEWER_SCREENER, UserRole.REVIEWER.value)
REVIEWER_BEN_HEADERS = build_user_headers(REVIEWER_VETTER, UserRole.REVIEWER.value)


def reviewer_headers(reviewer_id: str) -> Dict[str, str]:
    """Headers for a Reviewer acting under the given opaque identifier."""
    return build_user_headers(reviewer_id, UserRole.REVIEWER.value)


# ── Entity-backed roles ────────────────────────────────────────────────────

def make_teacher_headers(teacher_id: str) -> Dict[str, str]:
    """Headers for the Teacher role acting as the teacher with this id.

    Required whenever the call is ownership-gated (creating or editing a
    project, confirming a delivery, submitting a thank-you package).
    """
    return build_user_headers(teacher_id, UserRole.TEACHER.value)


def make_donor_headers(donor_id: str) -> Dict[str, str]:
    """Headers for the Donor role acting as the donor with this id."""
    return build_user_headers(donor_id, UserRole.DONOR.value)


def make_vendor_headers(vendor_id: str) -> Dict[str, str]:
    """Headers for the Vendor role acting as the vendor with this id."""
    return build_user_headers(vendor_id, UserRole.VENDOR.value)
