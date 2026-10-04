"""Pre-built role headers for every role in the API.

Six roles carry an opaque operator identity; a Subscriber's X-User-ID is the
id of the acting SubscriberContract, so that role needs a per-instance builder.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "print_ops_headers": build_user_headers("test-print-ops-1", "PrintOperationsDirector"),
    "delivery_manager_headers": build_user_headers("test-delivery-manager-1", "DeliveryNetworkManager"),
    "newsroom_manager_headers": build_user_headers("test-newsroom-manager-1", "NewsroomOperationsManager"),
    "customer_service_headers": build_user_headers("test-customer-service-1", "CustomerService"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # Subscriber is entity_backed:SubscriberContract — the shared constant below is
    # only for calls that do not exercise ownership. Use make_subscriber_headers()
    # with the real contract id for any ownership-gated call.
    "subscriber_headers": build_user_headers("test-subscriber-1", "Subscriber"),
}

# Convenience aliases used by fixtures and tests.
PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]
DELIVERY_MANAGER = TEST_USERS["delivery_manager_headers"]
NEWSROOM_MANAGER = TEST_USERS["newsroom_manager_headers"]
CUSTOMER_SERVICE = TEST_USERS["customer_service_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
SUBSCRIBER = TEST_USERS["subscriber_headers"]

# A second NewsroomOperationsManager operator, used to satisfy the
# segregation-of-duties rule (approval must not come from the creator).
NEWSROOM_MANAGER_ALT = build_user_headers("test-newsroom-manager-2", "NewsroomOperationsManager")


def make_print_ops_headers(user_id: str) -> dict:
    """PrintOperationsDirector headers for a specific operator id."""
    return build_user_headers(user_id, "PrintOperationsDirector")


def make_newsroom_manager_headers(user_id: str) -> dict:
    """NewsroomOperationsManager headers for a specific operator id."""
    return build_user_headers(user_id, "NewsroomOperationsManager")


def make_customer_service_headers(user_id: str) -> dict:
    """CustomerService headers for a specific operator id."""
    return build_user_headers(user_id, "CustomerService")


def make_delivery_manager_headers(user_id: str) -> dict:
    """DeliveryNetworkManager headers for a specific operator id."""
    return build_user_headers(user_id, "DeliveryNetworkManager")


def make_subscriber_headers(subscriber_contract_id: str) -> dict:
    """Subscriber headers acting as the owner of subscriber_contract_id.

    Subscriber.identity is entity_backed:SubscriberContract, so X-User-ID must be
    the actual contract id for any ownership-gated call.
    """
    return build_user_headers(subscriber_contract_id, "Subscriber")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor headers for a specific operator id."""
    return build_user_headers(user_id, "Auditor")