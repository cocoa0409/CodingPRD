"""Priority pairs: state versus constraint races on a single request."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_error,
)

from test_helpers.fixtures import (
    activate_addon,
    create_addon,
    get_addon,
    get_subscriber,
    set_clock,
    setup_activated_subscriber,
)


def test_activating_an_illegal_window_add_on_for_a_suspended_subscriber(api):
    """PRD §3.8: "A requested add-on opens in `REQUESTED` with `addon_price_cents` at 0."
    PRD §3.3: "While suspended, the subscriber cannot take new add-ons — the attempt is rejected with
    `ERR_SUBSCRIBER_NOT_ACTIVE` (HTTP 409)."

    The add-on carries a legal 30-day window so that the subscriber-state gate is what
    decides; an illegal window is refused on the request itself per PRD 3.8.

    Design: Difficulty/priority_pair_validation_conflict/add_on_activation_while_suspended_priority_pair
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]
    api.suspend_subscriber(subscriber_id, TEST_USERS["agent_headers"])
    assert get_subscriber(subscriber_id)["subscriber_status"] == "SUSPENDED"

    addon = create_addon(
        subscriber_id, addon_type="ROAMING", addon_days=30, per_day_allotment_mb=500
    )
    assert addon["addon_status"] == "REQUESTED"
    assert addon["addon_days"] == 30

    resp = api.activate_addon(addon["id"], TEST_USERS["planner_headers"])
    validate_error(resp, ApiErrorId.ERR_SUBSCRIBER_NOT_ACTIVE)

    after = get_addon(addon["id"])
    assert after["addon_status"] == "REQUESTED"
    assert after["addon_price_cents"] == 0


def test_resuming_the_subscriber_makes_the_same_activation_reachable(api):
    """PRD §3.8: "Activation also sets `start_at` to the current logical clock and derives `end_at`
    as `start_at` plus `addon_days` calendar days".

    Design: Difficulty/priority_pair_validation_conflict/add_on_activation_while_suspended_priority_pair
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]
    api.suspend_subscriber(subscriber_id, TEST_USERS["agent_headers"])

    addon = create_addon(
        subscriber_id, addon_type="ROAMING", addon_days=7, per_day_allotment_mb=500
    )
    blocked = api.activate_addon(addon["id"], TEST_USERS["planner_headers"])
    validate_error(blocked, ApiErrorId.ERR_SUBSCRIBER_NOT_ACTIVE)

    api.resume_subscriber(subscriber_id, TEST_USERS["agent_headers"])
    activated = activate_addon(addon["id"])
    assert activated["addon_status"] == "ACTIVE"
    assert activated["addon_price_cents"] == 273
    assert activated["start_at"].startswith("2026-10-01T00:00:00")
    assert activated["end_at"].startswith("2026-10-08T00:00:00")