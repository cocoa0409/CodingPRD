"""Caller identities for the four declared roles.

Every request carries ``X-User-ID`` and ``X-User-Role``. PlatformAdmin and
ComplianceReviewer identifiers are opaque; Consumer identifiers are the
client-supplied ``consumer_ref``; Recipient is entity-backed, so the acting
user's identifier must equal the Recipient row's ``id``.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Distinct opaque operator/reviewer ids so segregation-of-duties checks pass
# when a fixture composes creator / approver / suspender steps.
PLATFORM_ADMIN_1 = "admin_1"
PLATFORM_ADMIN_2 = "admin_2"
REVIEWER_1 = "reviewer_1"
REVIEWER_2 = "reviewer_2"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_1, "PlatformAdmin"),
    "platform_admin_2_headers": build_user_headers(PLATFORM_ADMIN_2, "PlatformAdmin"),
    "compliance_reviewer_headers": build_user_headers(REVIEWER_1, "ComplianceReviewer"),
    "compliance_reviewer_2_headers": build_user_headers(REVIEWER_2, "ComplianceReviewer"),
}


def make_admin_headers(user_id: str = PLATFORM_ADMIN_1) -> Dict[str, str]:
    """PlatformAdmin headers; the id is opaque but recorded on decisions."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_reviewer_headers(user_id: str = REVIEWER_1) -> Dict[str, str]:
    """ComplianceReviewer headers; the id is compared across review decisions."""
    return build_user_headers(user_id, "ComplianceReviewer")


def make_consumer_headers(consumer_ref: str) -> Dict[str, str]:
    """Consumer headers; X-User-ID must equal the consumer_ref on the resource."""
    return build_user_headers(consumer_ref, "Consumer")


def make_recipient_headers(recipient_id: str) -> Dict[str, str]:
    """Recipient headers; X-User-ID must equal the Recipient entity's id."""
    return build_user_headers(recipient_id, "Recipient")


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
