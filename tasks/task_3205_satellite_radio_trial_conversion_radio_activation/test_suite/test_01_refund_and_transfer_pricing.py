"""Refund and transfer-proration arithmetic: the pinned floor variants.

Covers Difficulty/dual_variant_calc and Difficulty/compensating_invariant
instances whose assertions live on the billing ledger.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ApiErrorId,
    assert_ledger_entry,
    fixtures,
    ledger_amount_of,
    ledger_entries_of,
)
from test_helpers.fixtures import ADMIN, SYSOP


def test_cancel_refund_floor_variant_on_paid_sub(api):
    """PRD §3.6: "The unused time is the whole number of days between the
    cancellation time and `end_at` — the difference in seconds divided by
    86400, floored. The refund is the subscription's `current_term_price_cents`
    multiplied by those unused days and divided by the plan's
    `term_length_days`, floored."

    10 days elapsed of a 30-day, 6000-cent term leaves 20 unused days, so the
    refund is floor(6000*20/30) = 4000; the ceil-days alternative would give
    4200 and is explicitly not the API's behavior ("an alternative
    ceiling-based reading is explicitly not the API's behavior").

    Design: Difficulty/dual_variant_calc/cancel_refund_floor_variant_on_paid_sub
    """
    customer, vehicle, radio, plan, sub = fixtures.setup_active_paid_sub(
        api, price_cents=6000, term_days=30, auto_renew=False
    )
    fixtures.set_clock(api, "2026-09-11T00:00:00Z")

    resp = api.cancel_subscription(
        sub["id"], {"effective_mode": "IMMEDIATE"}, fixtures.customer_headers(customer)
    )
    data = validate_success(resp)
    assert data["status"] == "CANCELLED"

    entries = fixtures.ledger_entries(api, sub["id"])
    for e in entries:
        assert_ledger_entry(e)
    credit = ledger_amount_of(entries, "PRORATION_CREDIT")
    assert credit == -4000, f"expected floor refund -4000, got {credit}"


def test_cancel_refund_floor_rejects_ceiling_reading(api):
    """PRD §3.6: "The cancellation refund rule is pinned to floor arithmetic,
    and an alternative ceiling-based reading is explicitly not the API's
    behavior."

    With 29 whole days remaining on a 30-day, 9000-cent term the floor refund
    is floor(9000*29/30) = 8700; a ceiling on the day count would refund the
    full 9000 and must not appear.

    Design: Difficulty/dual_variant_calc/cancel_refund_floor_variant_on_paid_sub
    """
    customer, vehicle, radio, plan, sub = fixtures.setup_active_paid_sub(
        api, price_cents=9000, term_days=30, auto_renew=False
    )
    fixtures.set_clock(api, "2026-09-02T00:00:00Z")  # 1 day elapsed, 29 remain

    resp = api.cancel_subscription(
        sub["id"], {"effective_mode": "IMMEDIATE"}, fixtures.customer_headers(customer)
    )
    validate_success(resp)

    entries = fixtures.ledger_entries(api, sub["id"])
    credit = ledger_amount_of(entries, "PRORATION_CREDIT")
    assert credit == -8700, f"expected -8700, got {credit}"
    assert credit != -9000, "ceiling-day reading refunded the whole term"


def _setup_transfer_world(api, price_cents=9000):
    """Old owner with an ACTIVE paid sub on a USED vehicle's GEN1 radio, plus
    a new-owner customer and a trial plan. Clock stays at the default."""
    old_owner = fixtures.create_customer(api, household_size=1)
    new_owner = fixtures.create_customer(api, household_size=1)
    tier = fixtures.create_tier(api, includes_streaming=True,
                                min_hardware_generation="GEN1")
    paid_plan = fixtures.create_paid_plan(
        api, tier["id"], service_mode="IN_VEHICLE", term_kind="MONTHLY",
        term_length_days=30, price_cents=price_cents, auto_renew_default=False,
    )
    trial_plan = fixtures.create_trial_plan(
        api, tier["id"], term_length_days=90,
    )
    automaker = fixtures.create_automaker(api)
    vehicle = fixtures.create_vehicle(api, automaker["id"], old_owner["id"],
                                      condition="USED", model_year=2020)
    radio = fixtures.create_radio(api, vehicle["id"], hardware_generation="GEN1")
    sub = fixtures.create_paid_radio_subscription(
        api, old_owner, paid_plan, radio, auto_renew=False
    )
    sub = fixtures.activate_subscription(api, sub, radio["id"])
    return old_owner, new_owner, vehicle, radio, trial_plan, sub


def test_transfer_posts_adjustment_not_proration_credit(api):
    """PRD §3.10: "the old owner is credited for unused whole days — the same
    floor-based proration as cancellation, posting a negative
    `TRANSFER_ADJUSTMENT` entry per subscription, with trials crediting zero."

    At 10 days elapsed of a 30-day, 9000-cent term the credit is
    floor(9000*20/30) = 6000, posted as TRANSFER_ADJUSTMENT — an
    implementation reusing the cancellation entry_type fails this assertion.

    Design: Difficulty/dual_variant_calc/transfer_proration_variant_vs_cancel_refund_on_vehicle_transfer
    """
    old_owner, new_owner, vehicle, radio, trial_plan, sub = _setup_transfer_world(api)
    fixtures.set_clock(api, "2026-09-11T00:00:00Z")
    vehicle_now = validate_success(api.get_vehicle(vehicle["id"], ADMIN))

    resp = api.transfer_ownership(
        vehicle["id"],
        {
            "new_owner_customer_id": new_owner["id"],
            "expected_vehicle_version": vehicle_now["version"],
            "trial_plan_id": trial_plan["id"],
        },
        ADMIN,
    )
    validate_success(resp)

    entries = fixtures.ledger_entries(api, sub["id"])
    adjustment = ledger_amount_of(entries, "TRANSFER_ADJUSTMENT")
    assert adjustment == -6000, f"expected -6000, got {adjustment}"
    assert not ledger_entries_of(entries, "PRORATION_CREDIT"), (
        "transfer must not post a PRORATION_CREDIT"
    )


def test_transfer_creates_fresh_trial_and_moves_owner(api):
    """PRD §3.10: "when `trial_plan_id` is supplied, a fresh
    `PENDING_ACTIVATION` trial is created for the new owner and an `ACTIVATE`
    signal is enqueued. The fresh trial's `origin` is `USED_DEALER` when a
    `used_dealer_id` accompanied the transfer and `TRANSFER_IN` otherwise".
    PRD §3.10: "The transfer rewrites `owner_customer_id` to the new owner".

    Design: Difficulty/dual_variant_calc/transfer_proration_variant_vs_cancel_refund_on_vehicle_transfer
    """
    old_owner, new_owner, vehicle, radio, trial_plan, sub = _setup_transfer_world(api)
    fixtures.set_clock(api, "2026-09-11T00:00:00Z")
    vehicle_now = validate_success(api.get_vehicle(vehicle["id"], ADMIN))

    resp = api.transfer_ownership(
        vehicle["id"],
        {
            "new_owner_customer_id": new_owner["id"],
            "expected_vehicle_version": vehicle_now["version"],
            "trial_plan_id": trial_plan["id"],
        },
        ADMIN,
    )
    data = validate_success(resp)
    assert data["owner_customer_id"] == new_owner["id"]

    old_sub = validate_success(api.get_subscription(sub["id"], ADMIN))
    assert old_sub["status"] == "TRANSFERRED_AWAY"

    radio_subs = validate_success(
        api.list_radio_subscriptions(radio["id"], ADMIN)
    )
    trials = [
        s for s in radio_subs
        if s["customer_id"] == new_owner["id"] and s["kind"] == "TRIAL"
    ]
    assert len(trials) == 1, f"expected one fresh trial, got {trials}"
    trial = trials[0]
    assert trial["status"] == "PENDING_ACTIVATION"
    assert trial["origin"] == "TRANSFER_IN"


def test_ledger_conservation_under_cancel_refund(api):
    """PRD §3.11: "Every monetary event lands in an append-only
    `BillingLedgerEntry` ... a signed `amount_cents` — charges positive,
    credits and refunds negative".
    PRD §3.6: "The refund is the subscription's `current_term_price_cents`
    multiplied by those unused days and divided by the plan's
    `term_length_days`, floored."

    After 10 of 30 days on a 9000-cent term, CHARGE (9000) plus
    PRORATION_CREDIT (-6000) nets exactly 3000 — the price retained for the
    elapsed whole days; a one-cent drift violates conservation.

    Design: Difficulty/compensating_invariant/ledger_conservation_under_cancel_refund
    """
    customer, vehicle, radio, plan, sub = fixtures.setup_active_paid_sub(
        api, price_cents=9000, term_days=30, auto_renew=False
    )
    fixtures.set_clock(api, "2026-09-11T00:00:00Z")

    resp = api.cancel_subscription(
        sub["id"], {"effective_mode": "IMMEDIATE"}, fixtures.customer_headers(customer)
    )
    validate_success(resp)

    entries = fixtures.ledger_entries(api, sub["id"])
    total = sum(e["amount_cents"] for e in entries)
    assert total == 3000, f"ledger net must equal retained 3000, got {total}"


def test_ledger_conservation_retained_equals_floor_elapsed_share(api):
    """PRD §3.6: "The unused time is the whole number of days between the
    cancellation time and `end_at` — the difference in seconds divided by
    86400, floored."

    Cancelling one second before the first day completes leaves 29 whole days,
    so CHARGE + PRORATION_CREDIT retains floor(9000*1/30) == 300 exactly.

    Design: Difficulty/compensating_invariant/ledger_conservation_under_cancel_refund
    """
    customer, vehicle, radio, plan, sub = fixtures.setup_active_paid_sub(
        api, price_cents=9000, term_days=30, auto_renew=False
    )
    fixtures.set_clock(api, "2026-09-01T23:59:59Z")

    resp = api.cancel_subscription(
        sub["id"], {"effective_mode": "IMMEDIATE"}, fixtures.customer_headers(customer)
    )
    validate_success(resp)

    entries = fixtures.ledger_entries(api, sub["id"])
    total = sum(e["amount_cents"] for e in entries)
    assert total == 300, f"expected retained 300 (floor(9000*1/30)), got {total}"
