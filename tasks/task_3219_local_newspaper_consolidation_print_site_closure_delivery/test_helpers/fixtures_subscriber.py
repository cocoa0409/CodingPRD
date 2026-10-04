"""
Composite setup helpers — subscriber contracts, retention and frequency flows.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_subscriber_payload,
    create_retention_action_payload,
)
from .test_users import (
    CUSTOMER_SERVICE,
    PRINT_OPS,
    DELIVERY_MANAGER,
    make_subscriber_headers,
)
from .constants import CLOCK_2026_09_30


# ─── Subscriber contracts ────────────────────────────────────────────

def create_subscriber(stop_id, **overrides):
    """Create a subscriber contract on a delivery stop. Returns the contract."""
    return get_success_data(api_client.create_subscriber(
        stop_id, create_subscriber_payload(**overrides), CUSTOMER_SERVICE))


def create_subscriber_response(stop_id, **overrides):
    """Create a subscriber and return the raw Response (for error paths)."""
    return api_client.create_subscriber(
        stop_id, create_subscriber_payload(**overrides), CUSTOMER_SERVICE)


def get_subscriber(subscriber_id, headers=None):
    """Read a subscriber contract. Pass Subscriber headers to exercise ownership."""
    return get_success_data(api_client.get_subscriber(
        subscriber_id, headers or CUSTOMER_SERVICE))


def get_subscriber_response(subscriber_id, headers=None):
    """Read a subscriber and return the raw Response (for error paths)."""
    return api_client.get_subscriber(subscriber_id, headers or CUSTOMER_SERVICE)


def list_subscribers(params=None):
    """List subscriber contracts, optionally filtered."""
    return get_success_data(api_client.list_subscribers(CUSTOMER_SERVICE, params))


def list_stop_subscribers(stop_id):
    """List the subscriber contracts on a stop."""
    return get_success_data(api_client.list_stop_subscribers(stop_id, CUSTOMER_SERVICE))


def migrate_subscriber(subscriber_id, as_subscriber=False):
    """Migrate a subscriber to digital. as_subscriber acts as the owner."""
    headers = make_subscriber_headers(subscriber_id) if as_subscriber else CUSTOMER_SERVICE
    return get_success_data(api_client.migrate_subscriber(subscriber_id, headers))


def migrate_subscriber_response(subscriber_id, headers=None):
    """Migrate a subscriber and return the raw Response."""
    return api_client.migrate_subscriber(subscriber_id, headers or CUSTOMER_SERVICE)


def cancel_subscriber(subscriber_id, as_subscriber=False):
    """Cancel a subscriber contract."""
    headers = make_subscriber_headers(subscriber_id) if as_subscriber else CUSTOMER_SERVICE
    return get_success_data(api_client.cancel_subscriber(subscriber_id, headers))


def cancel_subscriber_response(subscriber_id, headers=None):
    """Cancel a subscriber and return the raw Response."""
    return api_client.cancel_subscriber(subscriber_id, headers or CUSTOMER_SERVICE)


def refund_subscriber(subscriber_id):
    """Refund a subscriber's remaining print issues."""
    return get_success_data(api_client.refund_subscriber(subscriber_id, CUSTOMER_SERVICE))


def refund_subscriber_response(subscriber_id):
    """Refund a subscriber and return the raw Response."""
    return api_client.refund_subscriber(subscriber_id, CUSTOMER_SERVICE)


def accept_retention_offer(subscriber_id):
    """Accept the open retention offer and return the subscriber to active."""
    return get_success_data(api_client.accept_retention_offer(
        subscriber_id, CUSTOMER_SERVICE))


def accept_retention_offer_response(subscriber_id):
    """Accept the open retention offer and return the raw Response."""
    return api_client.accept_retention_offer(subscriber_id, CUSTOMER_SERVICE)


# ─── Retention actions ───────────────────────────────────────────────

def offer_retention_action(subscriber_id, **overrides):
    """Offer a retention action to a churning subscriber."""
    return get_success_data(api_client.offer_retention_action(
        subscriber_id, create_retention_action_payload(**overrides), CUSTOMER_SERVICE))


def offer_retention_action_response(subscriber_id, headers=None, **overrides):
    """Offer a retention action and return the raw Response (for RBAC paths)."""
    return api_client.offer_retention_action(
        subscriber_id, create_retention_action_payload(**overrides),
        headers or CUSTOMER_SERVICE)


def list_retention_actions(subscriber_id):
    """List the retention actions on a subscriber contract."""
    return get_success_data(api_client.list_subscriber_retention_actions(
        subscriber_id, CUSTOMER_SERVICE))


def get_retention_action(action_id):
    """Read one retention action."""
    return get_success_data(api_client.get_retention_action(action_id, CUSTOMER_SERVICE))


def accept_retention_action(action_id):
    """Accept a retention action inside its cooling-off window."""
    return get_success_data(api_client.accept_retention_action(action_id, CUSTOMER_SERVICE))


def accept_retention_action_response(action_id):
    """Accept a retention action and return the raw Response (for error paths)."""
    return api_client.accept_retention_action(action_id, CUSTOMER_SERVICE)


# ─── Chain: stop termination seeds the retention branch ──────────────

def setup_subscriber_in_retention(stop_id, subscriber_overrides=None,
                                  clock=CLOCK_2026_09_30):
    """Create a subscriber then terminate its stop, seeding churned_pending_retention.

    Returns (subscriber_after_termination, stop_after_termination).
    """
    subscriber = create_subscriber(stop_id, **(subscriber_overrides or {}))
    stop = terminate_stop(stop_id)
    return get_subscriber(subscriber["id"]), stop


def setup_subscriber_with_open_retention_action(stop_id, subscriber_overrides=None,
                                                action_overrides=None):
    """Subscriber on a stop, stop terminated, one open retention action offered.

    Returns (subscriber, stop, action).
    """
    subscriber, stop = setup_subscriber_in_retention(
        stop_id, subscriber_overrides=subscriber_overrides)
    action = offer_retention_action(subscriber["id"], **(action_overrides or {}))
    return subscriber, stop, action


def terminate_stop(stop_id):
    """Terminate a delivery stop. Returns the stop dict."""
    from .fixtures_delivery import terminate_stop as _terminate
    return _terminate(stop_id)


def terminate_contractor(contractor_id):
    """Terminate a delivery contractor. Returns the contractor dict."""
    from .fixtures_delivery import terminate_contractor as _terminate
    return _terminate(contractor_id)


# ─── Frequency reduction flow ────────────────────────────────────────

def open_frequency_change(market_id, target_per_week):
    """Open a print frequency reduction on the market."""
    return get_success_data(api_client.open_frequency_change(
        market_id, {"target_print_edition_per_week": target_per_week}, PRINT_OPS))


def open_frequency_change_response(market_id, target_per_week):
    """Open a frequency change and return the raw Response."""
    return api_client.open_frequency_change(
        market_id, {"target_print_edition_per_week": target_per_week}, PRINT_OPS)


def dispatch_frequency_notices(market_id):
    """Dispatch the subscriber notices for the open reduction."""
    return get_success_data(api_client.dispatch_frequency_notices(market_id, PRINT_OPS))


def dispatch_frequency_notices_response(market_id):
    """Dispatch notices and return the raw Response (for hold paths)."""
    return api_client.dispatch_frequency_notices(market_id, PRINT_OPS)


def apply_frequency_change(market_id):
    """Apply the lowered print frequency."""
    return get_success_data(api_client.apply_frequency_change(market_id, PRINT_OPS))


def apply_frequency_change_response(market_id):
    """Apply the frequency change and return the raw Response."""
    return api_client.apply_frequency_change(market_id, PRINT_OPS)


def reject_frequency_change(market_id):
    """Reject the open frequency reduction."""
    return get_success_data(api_client.reject_frequency_change(market_id, PRINT_OPS))


def setup_market_at_notices_dispatched(market_id, target_per_week=3,
                                       subscriber_id=None, subscriber_headers=None):
    """Open + dispatch the reduction, and accept one renewal so apply is reachable.

    Returns the market dict after dispatch.
    """
    from .fixtures import set_clock

    open_frequency_change(market_id, target_per_week)
    market = dispatch_frequency_notices(market_id)
    if subscriber_id is not None:
        # A migrated renewal counts toward renewals_accepted_count.
        migrate_subscriber(subscriber_id)
    return market