"""Pre-built identity headers for every role the PRD declares.

For `OrganizationRep` the `X-User-ID` is the `id` of the acting `Organization`,
so ownership-gated calls must always use `make_organization_rep_headers()` with
the real organization id. Every other role carries an opaque operator id.
"""
from prd_bench_local_runner.testing import build_user_headers

ANALYST_USER_ID = "analyst-1"
OTHER_ANALYST_USER_ID = "analyst-2"
REVIEWER_USER_ID = "reviewer-1"
OTHER_REVIEWER_USER_ID = "reviewer-2"
ADMIN_USER_ID = "admin-1"
OTHER_ADMIN_USER_ID = "admin-2"
PANELIST_USER_IDS = ["panel-1", "panel-2", "panel-3"]
ALT_PANELIST_USER_IDS = ["panel-a", "panel-b", "panel-c"]
PUBLIC_USER_ID = "public-1"

TEST_USERS = {
    "analyst_headers": build_user_headers(ANALYST_USER_ID, "RatingAnalyst"),
    "other_analyst_headers": build_user_headers(OTHER_ANALYST_USER_ID, "RatingAnalyst"),
    "reviewer_headers": build_user_headers(REVIEWER_USER_ID, "PublishingReviewer"),
    "other_reviewer_headers": build_user_headers(
        OTHER_REVIEWER_USER_ID, "PublishingReviewer"
    ),
    "admin_headers": build_user_headers(ADMIN_USER_ID, "MethodologyAdmin"),
    "other_admin_headers": build_user_headers(OTHER_ADMIN_USER_ID, "MethodologyAdmin"),
    "panelist_headers": build_user_headers(PANELIST_USER_IDS[0], "AppealPanelist"),
    "public_headers": build_user_headers(PUBLIC_USER_ID, "PublicUser"),
    # Fallback only — never use for an ownership-gated call.
    "org_rep_headers": build_user_headers("org-rep-1", "OrganizationRep"),
}


def make_analyst_headers(user_id: str) -> dict:
    """Headers for a `RatingAnalyst` acting under an arbitrary operator id."""
    return build_user_headers(user_id, "RatingAnalyst")


def make_reviewer_headers(user_id: str) -> dict:
    """Headers for a `PublishingReviewer` acting under an arbitrary operator id."""
    return build_user_headers(user_id, "PublishingReviewer")


def make_admin_headers(user_id: str) -> dict:
    """Headers for a `MethodologyAdmin` acting under an arbitrary operator id."""
    return build_user_headers(user_id, "MethodologyAdmin")


def make_panelist_headers(user_id: str) -> dict:
    """Headers for an `AppealPanelist`; the id must appear in the seated panel."""
    return build_user_headers(user_id, "AppealPanelist")


def make_public_headers(user_id: str) -> dict:
    """Headers for a `PublicUser` acting under an arbitrary operator id."""
    return build_user_headers(user_id, "PublicUser")


def make_organization_rep_headers(organization_id: str) -> dict:
    """Headers for an `OrganizationRep`; `X-User-ID` is the Organization's own id."""
    return build_user_headers(organization_id, "OrganizationRep")


def headers_for_role(role: str, user_id: str) -> dict:
    """Headers for any declared role under an explicit acting identifier."""
    return build_user_headers(user_id, role)
