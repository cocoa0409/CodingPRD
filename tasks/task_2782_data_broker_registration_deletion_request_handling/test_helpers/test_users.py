"""Pre-built role headers for every role in the PRD.

Two roles are entity backed: a BrokerAdmin's X-User-ID is the DataBroker's id and
a Consumer's X-User-ID is the Consumer's id. For those roles the shared constants
below are only usable by tests that do not depend on resource ownership; every
ownership-gated call must go through the make_*_headers() builders with the real
entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque-role identifiers. Two distinct privacy reviewers exist because the
# reviewer who decided a verification may not be the one who executes it.
REVIEWER_ALPHA_ID = "reviewer-alpha"
REVIEWER_BETA_ID = "reviewer-beta"
INTAKE_AGENT_ID = "intake-agent-1"
STATE_PLATFORM_ID = "state-platform-1"
REGULATOR_ID = "regulator-1"
PLATFORM_ADMIN_ID = "platform-admin-1"

TEST_USERS = {
    # entity_backed:DataBroker — fallback for non-ownership tests only.
    "broker_admin_headers": build_user_headers("test-broker-admin-1", "BrokerAdmin"),
    # entity_backed:Consumer — fallback for non-ownership tests only.
    "consumer_headers": build_user_headers("test-consumer-1", "Consumer"),
    # opaque roles — the shared constant is the canonical form.
    "intake_agent_headers": build_user_headers(INTAKE_AGENT_ID, "IntakeAgent"),
    "privacy_reviewer_headers": build_user_headers(REVIEWER_ALPHA_ID, "PrivacyReviewer"),
    "privacy_reviewer_beta_headers": build_user_headers(
        REVIEWER_BETA_ID, "PrivacyReviewer"
    ),
    "state_platform_headers": build_user_headers(STATE_PLATFORM_ID, "StatePlatform"),
    "regulator_headers": build_user_headers(REGULATOR_ID, "Regulator"),
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
}

# Convenience aliases for the two reviewers used across verification workflows.
REVIEWER_ALPHA_HEADERS = TEST_USERS["privacy_reviewer_headers"]
REVIEWER_BETA_HEADERS = TEST_USERS["privacy_reviewer_beta_headers"]


def make_broker_admin_headers(user_id: str) -> dict:
    """For BrokerAdmin (entity backed by DataBroker). Pass the DataBroker.id
    whenever the call is scoped to that broker's own resources."""
    return build_user_headers(user_id, "BrokerAdmin")


def make_consumer_headers(user_id: str) -> dict:
    """For Consumer (entity backed by Consumer). Pass the Consumer.id whenever
    the call is scoped to that consumer's own resources."""
    return build_user_headers(user_id, "Consumer")


def make_intake_agent_headers(user_id: str = INTAKE_AGENT_ID) -> dict:
    return build_user_headers(user_id, "IntakeAgent")


def make_privacy_reviewer_headers(user_id: str = REVIEWER_ALPHA_ID) -> dict:
    """PrivacyReviewer identities are opaque, but distinct ids matter: the
    verification decider is barred from executing the same deletion."""
    return build_user_headers(user_id, "PrivacyReviewer")


def make_state_platform_headers(user_id: str = STATE_PLATFORM_ID) -> dict:
    return build_user_headers(user_id, "StatePlatform")


def make_regulator_headers(user_id: str = REGULATOR_ID) -> dict:
    return build_user_headers(user_id, "Regulator")


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_headers(user_id: str, role: str) -> dict:
    """Escape hatch for authorization tests that need an arbitrary pairing."""
    return build_user_headers(user_id, role)
