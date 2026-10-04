"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlatformOps, ContentModerator,
# TrustInvestigator, SupportAdmin, LegalOps) and for tests that do not exercise
# ownership. For entity-backed roles (Reviewer, BusinessOwner, Advertiser,
# Reporter) the shared constant is a fallback only; ownership-gated calls must
# use the make_*_headers builders with the actual User id.
TEST_USERS = {
    "platform_ops_headers": build_user_headers("test-platform-ops-1", "PlatformOps"),
    "content_moderator_headers": build_user_headers("test-content-moderator-1", "ContentModerator"),
    "trust_investigator_headers": build_user_headers("test-trust-investigator-1", "TrustInvestigator"),
    "support_admin_headers": build_user_headers("test-support-admin-1", "SupportAdmin"),
    "legal_ops_headers": build_user_headers("test-legal-ops-1", "LegalOps"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "Reviewer"),
    "business_owner_headers": build_user_headers("test-business-owner-1", "BusinessOwner"),
    "advertiser_headers": build_user_headers("test-advertiser-1", "Advertiser"),
    "reporter_headers": build_user_headers("test-reporter-1", "Reporter"),
}


def make_reviewer_headers(user_id: str) -> dict:
    """Reviewer is entity-backed by User: X-User-ID must equal the author's id."""
    return build_user_headers(user_id, "Reviewer")


def make_business_owner_headers(user_id: str) -> dict:
    """BusinessOwner is entity-backed by User: X-User-ID must equal the User id,
    and must match page.claimed_by_user_id for owner-gated operations."""
    return build_user_headers(user_id, "BusinessOwner")


def make_advertiser_headers(user_id: str) -> dict:
    """Advertiser is entity-backed by User: X-User-ID must equal the User id,
    and must match ad_account.owner_user_id for account/campaign mutations."""
    return build_user_headers(user_id, "Advertiser")


def make_reporter_headers(user_id: str) -> dict:
    """Reporter is entity-backed by User: X-User-ID must equal the reporter's id."""
    return build_user_headers(user_id, "Reporter")


def make_content_moderator_headers(user_id: str) -> dict:
    """ContentModerator is opaque, but a distinct X-User-ID is needed for
    segregation-of-duties scenarios (moderator must not be the filer)."""
    return build_user_headers(user_id, "ContentModerator")


def make_trust_investigator_headers(user_id: str) -> dict:
    """TrustInvestigator is opaque, but a distinct X-User-ID is needed for
    segregation-of-duties scenarios (investigator must not be the reporter)."""
    return build_user_headers(user_id, "TrustInvestigator")
