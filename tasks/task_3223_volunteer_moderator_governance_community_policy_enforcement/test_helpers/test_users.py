"""Pre-built role headers for every role the platform recognises."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles, and for tests whose success does
# not depend on the caller owning the subject resource.
TEST_USERS = {
    # Account and Moderator are both entity-backed, so the shared constants are
    # fallbacks for calls that are not ownership-gated.
    "account_headers": build_user_headers("test-account-1", "Account"),
    "moderator_headers": build_user_headers("test-moderator-1", "Moderator"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "content_reviewer_headers": build_user_headers("test-reviewer-1", "ContentReviewer"),
    "succession_auditor_headers": build_user_headers("test-auditor-1", "SuccessionAuditor"),
}


def make_account_headers(user_id: str) -> dict:
    """For Account (entity_backed:Account). Pass the acting Account.id whenever the
    call is ownership-gated."""
    return build_user_headers(user_id, "Account")


def make_moderator_headers(moderator_id: str) -> dict:
    """For Moderator (entity_backed:Moderator). Pass the actual Moderator row id
    whenever the call is ownership-gated."""
    return build_user_headers(moderator_id, "Moderator")


def make_platform_admin_headers(operator_id: str = "test-admin-1") -> dict:
    """For PlatformAdmin (opaque identity)."""
    return build_user_headers(operator_id, "PlatformAdmin")


def make_anonymous_headers(reader_id: str = "test-anonymous-1") -> dict:
    """For Anonymous (opaque identity)."""
    return build_user_headers(reader_id, "Anonymous")


def make_content_reviewer_headers(reviewer_id: str = "test-reviewer-1") -> dict:
    """For ContentReviewer (opaque identity)."""
    return build_user_headers(reviewer_id, "ContentReviewer")


def make_succession_auditor_headers(auditor_id: str = "test-auditor-1") -> dict:
    """For SuccessionAuditor (opaque identity)."""
    return build_user_headers(auditor_id, "SuccessionAuditor")