"""Role headers: shared constants plus per-instance builders for entity-backed roles."""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "planner_headers": build_user_headers("test-planner-1", "CapacityPlanner"),
    "agent_headers": build_user_headers("test-agent-1", "SupportAgent"),
    "fulfillment_headers": build_user_headers("test-fulfillment-1", "FulfillmentOperator"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # entity_backed:Subscriber — the shared constant is a fallback for calls
    # that are not ownership-gated. Ownership-gated calls must use the builder.
    "subscriber_headers": build_user_headers("test-subscriber-1", "Subscriber"),
    # entity_backed:RetailPartner — same rule applies.
    "partner_headers": build_user_headers("test-partner-1", "RetailPartner"),
}


def make_subscriber_headers(subscriber_id: str) -> dict:
    """For Subscriber (entity_backed:Subscriber). Pass the actual Subscriber.id as
    the user id whenever the call is ownership-gated."""
    return build_user_headers(subscriber_id, "Subscriber")


def make_partner_headers(partner_id: str) -> dict:
    """For RetailPartner (entity_backed:RetailPartner). Pass the actual
    RetailPartner.id as the user id whenever the call is ownership-gated."""
    return build_user_headers(partner_id, "RetailPartner")