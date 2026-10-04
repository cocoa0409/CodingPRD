"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. For Agent / Consumer / ComparativeRater (entity-backed roles) the
# shared constant is a fallback only; ownership-gated calls must use the
# make_*_headers builders with the actual entity id.
TEST_USERS = {
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "carrier_admin_headers": build_user_headers("test-carrier-admin-1", "CarrierAdmin"),
    "rating_manager_headers": build_user_headers("test-rating-manager-1", "RatingManager"),
    "underwriting_reviewer_headers": build_user_headers("test-underwriting-reviewer-1", "UnderwritingReviewer"),
    "underwriting_reviewer_2_headers": build_user_headers("test-underwriting-reviewer-2", "UnderwritingReviewer"),
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
    "consumer_headers": build_user_headers("test-consumer-1", "Consumer"),
    "comparative_rater_headers": build_user_headers("test-comparative-rater-1", "ComparativeRater"),
    "system_headers": build_user_headers("test-system-1", "System"),
}


def make_agent_headers(agent_id: str) -> dict:
    """For Agent (entity-backed by Agent): X-User-ID must equal the acting
    agent's id whenever the call is ownership-gated (agent-channel quotes,
    agent-quote, bind, bundle placement, telematics actions)."""
    return build_user_headers(agent_id, "Agent")


def make_consumer_headers(consumer_id: str) -> dict:
    """For Consumer (entity-backed by Consumer): X-User-ID must equal the acting
    consumer's id whenever the call is ownership-gated (direct quotes, bind,
    cancel, refer-to-agent, telematics actions)."""
    return build_user_headers(consumer_id, "Consumer")


def make_comparative_rater_headers(rater_id: str) -> dict:
    """For ComparativeRater (entity-backed by ComparativeRater): X-User-ID must
    equal the acting rater's id whenever the call is ownership-gated."""
    return build_user_headers(rater_id, "ComparativeRater")
