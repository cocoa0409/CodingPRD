"""Role headers for the four roles PRD §2.1 declares.

Two of the four roles are entity-backed and the identity is compared against a
stored id, so those two must always be built from a real row:

PRD §2.1: "For the `Advertiser` role the `X-User-ID` header carries the
`Advertiser.id` of the acting advertising account, and the service compares it to
`AdCreative.advertiser_id`, `Certification.advertiser_id`, the `advertiser_id`
behind a `DisapprovalNotice`, and the `advertiser_id` behind the notice an
`Appeal` targets."

PRD §2.1: "For the `PolicyReviewer` role the `X-User-ID` header carries the
`Reviewer.id` of the acting reviewer and it must resolve to an existing
`Reviewer`."

The remaining two are opaque, so a shared constant is always a legitimate
identity for them:

PRD §2.1: "For the `IntegrityAnalyst` and `PolicyAdmin` roles the `X-User-ID`
header is an opaque operator identifier that the service never compares to any
stored id."
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "policy_admin_headers": build_user_headers("policy-admin-1", "PolicyAdmin"),
    "integrity_analyst_headers": build_user_headers(
        "integrity-analyst-1", "IntegrityAnalyst"
    ),
    # The two entity-backed roles have no meaningful shared identity: use
    # make_advertiser_headers / make_reviewer_headers with a real row id instead.
    "advertiser_headers": build_user_headers("advertiser-placeholder", "Advertiser"),
    "policy_reviewer_headers": build_user_headers(
        "reviewer-placeholder", "PolicyReviewer"
    ),
}


def make_advertiser_headers(advertiser_id: str) -> dict:
    """Headers for the advertising account whose `Advertiser.id` is given.

    Always pass the id of a real advertiser row: ownership of creatives,
    certifications, notices and appeals is decided by this header.
    """
    return build_user_headers(advertiser_id, "Advertiser")


def make_reviewer_headers(reviewer_id: str) -> dict:
    """Headers for the reviewer whose `Reviewer.id` is given.

    Always pass the id of a real reviewer row: task ownership, claim eligibility
    and appeal segregation of duties are all decided by this header.
    """
    return build_user_headers(reviewer_id, "PolicyReviewer")


def make_policy_admin_headers(user_id: str = "policy-admin-1") -> dict:
    """Headers for a platform policy operator (identity is opaque)."""
    return build_user_headers(user_id, "PolicyAdmin")


def make_integrity_analyst_headers(user_id: str = "integrity-analyst-1") -> dict:
    """Headers for an integrity analyst (identity is opaque)."""
    return build_user_headers(user_id, "IntegrityAnalyst")


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary identity / role pair.

    Used by the authentication probes, which deliberately send an empty identity,
    an empty role, or a role spelling that is not one of the four declared roles.
    """
    return build_user_headers(user_id, role)


# Convenience aliases for the two opaque roles.
ADMIN = TEST_USERS["policy_admin_headers"]
ANALYST = TEST_USERS["integrity_analyst_headers"]
