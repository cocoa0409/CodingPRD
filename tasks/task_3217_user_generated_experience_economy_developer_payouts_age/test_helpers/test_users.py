"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Creator is entity-backed by User: the shared constant is a
# fallback for non-ownership tests only; ownership-gated calls must use
# make_creator_headers with the acting user's id. Opaque operator roles
# (Moderator, AppealsReviewer, SafetyAgent, FinanceOfficer, PlatformAdmin) use
# their shared constants as the canonical form; segregation-of-duties tests
# build extra operator identities with build_user_headers directly.
TEST_USERS = {
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "creator_headers": build_user_headers("test-creator-1", "Creator"),
    "moderator_headers": build_user_headers("test-moderator-1", "Moderator"),
    "appeals_reviewer_headers": build_user_headers("test-appeals-reviewer-1", "AppealsReviewer"),
    "safety_agent_headers": build_user_headers("test-safety-agent-1", "SafetyAgent"),
    "finance_officer_headers": build_user_headers("officer-1", "FinanceOfficer"),
    "finance_officer_2_headers": build_user_headers("officer-2", "FinanceOfficer"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


def make_creator_headers(user_id: str) -> dict:
    """For Creator (entity-backed by User): X-User-ID must equal the acting
    user's id whenever the call is ownership-gated (own experiences, items,
    listings, purchases, devex requests, parental controls, appeals)."""
    return build_user_headers(user_id, "Creator")


def make_finance_officer_headers(officer_id: str) -> dict:
    """FinanceOfficer is opaque, but segregation-of-duties checks compare the
    recorded officer identifiers, so tests pick distinct officer ids."""
    return build_user_headers(officer_id, "FinanceOfficer")


def make_moderator_headers(moderator_id: str) -> dict:
    return build_user_headers(moderator_id, "Moderator")


def make_safety_agent_headers(agent_id: str) -> dict:
    return build_user_headers(agent_id, "SafetyAgent")
