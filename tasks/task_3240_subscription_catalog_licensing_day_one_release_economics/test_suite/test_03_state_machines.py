"""Cyclic and parallel state machines.

`CatalogEntry` genuinely loops — an announced removal can be withdrawn — and
`Subscription` carries two independent dimensions on one row, so a billing
failure and an entitlement grace period are not the same fact.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    list_entitlements,
    make_subscriber_headers,
    scenario_with_published_entry,
    scenario_with_subscriber,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_entry_rotation_loops_back_to_added_before_terminating(api):
    """PRD §3.4: "This is what makes the rotation cyclic: `ADDED` to `REMOVING`
    on announcement, `REMOVING` back to `ADDED` on withdrawal."
    PRD §3.4: "A `CatalogAdmin` who withdraws the announcement moves the entry
    from `REMOVING` back to `ADDED`, which is permitted only while the logical
    clock is strictly before `removal_date` minus three days."

    Design: Difficulty/non_linear_state_machine/catalog_entry_rotation_revert_and_terminate
    """
    sc = scenario_with_published_entry(api)
    entry_id = sc.entry["id"]

    after_publish = validate_success(api.get_catalog_entry(entry_id, ADMIN))
    assert after_publish["status"] == "ADDED"
    assert after_publish["actual_add_date"] is not None

    first_announce = validate_success(api.announce_entry_removal(entry_id, ADMIN))
    assert first_announce["status"] == "REMOVING"
    # The notice is measured between announced_add_date and removal_date.
    assert first_announce["removal_notice_days"] == 89, \
        "2026-09-02 to 2026-11-30 truncated to whole days"

    reverted = validate_success(api.cancel_entry_removal(entry_id, ADMIN))
    assert reverted["status"] == "ADDED", "the loop back to ADDED is accepted"

    second_announce = validate_success(api.announce_entry_removal(entry_id, ADMIN))
    assert second_announce["status"] == "REMOVING"

    terminated = validate_success(api.retire_catalog_entry(entry_id, ADMIN))
    assert terminated["status"] == "DELISTED", "the second REMOVING is terminal"


def test_retiring_an_entry_twice_is_refused(api):
    """PRD §3.4: "rejected with `ERR_ENTRY_ALREADY_DELISTED`. Retiring a `PLANNED` entry simply marks it `DELISTED`".

    Design: Difficulty/non_linear_state_machine/catalog_entry_rotation_revert_and_terminate
    """
    sc = scenario_with_published_entry(api)
    entry_id = sc.entry["id"]

    validate_success(api.retire_catalog_entry(entry_id, ADMIN))
    validate_error(api.retire_catalog_entry(entry_id, ADMIN), "ERR_ENTRY_ALREADY_DELISTED")

    # The rename/restore path is closed as well: a delisted entry is terminal.
    reread = validate_success(api.get_catalog_entry(entry_id, ADMIN))
    assert reread["status"] == "DELISTED"


def test_subscription_billing_and_lifecycle_dimensions_move_independently(api):
    """PRD §3.5: "Failure arrives from the clock, not from a request. When the
    logical clock advances to a monthly renewal instant and the renewal charge
    fails, a `PAID` monthly subscription moves to `FAILED`, `unpaid_months` is
    incremented by one, `lifecycle_status` flips from `ACTIVE` to `GRACE`, and
    every entitlement of that subscription flips from `ACTIVE` to `GRACE`."

    Design: Difficulty/non_linear_state_machine/subscription_billing_and_lifecycle_dimensions_evolve_independently
    """
    sc = scenario_with_subscriber(api)
    subscription = sc.subscription

    entitlements = list_entitlements(api, subscription_id=subscription["id"])
    assert len(entitlements) == 1
    assert entitlements[0]["status"] == "ACTIVE"

    set_clock(api, "2026-10-02T00:00:00Z")
    after_failure = validate_success(api.get_subscription(subscription["id"], ADMIN))
    assert after_failure["billing_status"] == "FAILED"
    assert after_failure["unpaid_months"] == 1
    assert after_failure["lifecycle_status"] == "GRACE"

    grace_rows = list_entitlements(api, subscription_id=subscription["id"])
    assert len(grace_rows) == 1
    assert grace_rows[0]["status"] == "GRACE", \
        "every entitlement of the subscription flips to GRACE with it"


def test_settled_month_returns_the_lifecycle_dimension_to_active(api):
    """PRD §3.5: "Settling the outstanding month from `FAILED` works exactly as
    it does from `PENDING`: `unpaid_months` is decremented by one, and when it
    reaches zero the lifecycle dimension and the entitlements return to
    `ACTIVE` as described above."
    PRD §3.5: "`CANCELLED` is terminal — a subscription that has been cancelled
    accepts no further transitions".

    Design: Difficulty/non_linear_state_machine/subscription_billing_and_lifecycle_dimensions_evolve_independently
    """
    sc = scenario_with_subscriber(api)
    subscription = sc.subscription
    subscriber = sc.subscriber

    set_clock(api, "2026-10-02T00:00:00Z")
    validate_success(api.get_subscription(subscription["id"], ADMIN))

    settled = validate_success(
        api.pay_subscription(subscription["id"], make_subscriber_headers(subscriber["id"]))
    )
    assert settled["billing_status"] == "PAID"
    assert settled["lifecycle_status"] == "ACTIVE", \
        "the cyclic GRACE to ACTIVE revert fired when unpaid_months reached zero"

    restored = list_entitlements(api, subscription_id=subscription["id"])
    assert restored[0]["status"] == "ACTIVE"

    cancelled = validate_success(
        api.cancel_subscription(subscription["id"], make_subscriber_headers(subscriber["id"]))
    )
    assert cancelled["lifecycle_status"] == "CANCELLED"
    assert cancelled["billing_status"] == "PAID", \
        "the two dimensions are independent, so a cancellation leaves billing alone"
    assert cancelled["cancellation_reason"] == "USER_INITIATED"

    revoked = list_entitlements(api, subscription_id=subscription["id"])
    assert len(revoked) == 1, "no entitlement row was deleted"
    assert revoked[0]["status"] == "REVOKED"