"""Cancellation: the waiver ladder's fixed order, and the deposit buckets that must
still add up afterwards.

The settlement splits the held deposit into a retained part and a refunded part, and
the tier that decides the split is the first one that holds, not the most generous one.
"""

import pytest

from test_helpers import (
    PROJECT_COORDINATOR,
    AssignmentStatus,
    DeliveryStatus,
    FinancialStatus,
    FulfillmentStatus,
    PermitStatus,
    ReleaseReason,
    WaiverTier,
    assert_committed_minutes,
    assert_deposit_buckets,
    assert_instant,
    assert_money,
    assert_project_dimensions,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_customer_headers,
)

DEPOSIT = 59002
QUOTED = 196673

COOLING_OFF_CLOCK = "2026-08-03T00:00:00.000Z"
LATE_CLOCK = "2026-08-11T00:00:00.000Z"
REINSTATE_CLOCK = "2026-08-12T00:00:00.000Z"


# ---------------------------------------------------------------------------
# The waiver ladder: tier two silences tier four
# ---------------------------------------------------------------------------
def _fourth_project_of_a_repeat_household(api):
    """One household with four projects — so the goodwill tier would hold — whose
    fourth project is cancelled two days after the sale."""
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.jurisdiction_payload())
    customer_id = base["customer"]["id"]
    projects = [
        fx.sell_project(api, base, estimated_units=420.00,
                        site_address=f"{n} Alder Row",
                        requested_install_date=f"2026-08-2{4 + n}T13:00:00.000Z")
        for n in (1, 2, 3, 4)
    ]
    fourth = fx.pay_deposit(api, projects[3], customer_id)
    delivery = fx.plan_delivery(
        api, fourth["id"],
        f.delivery_payload(promised_window_start="2026-08-10T08:00:00.000Z",
                           promised_window_end="2026-08-12T08:00:00.000Z"))
    delivery = fx.move_delivery(api, delivery["id"], DeliveryStatus.IN_TRANSIT)

    # Exactly 48 hours after every row above was created.
    fx.set_clock(api, COOLING_OFF_CLOCK)
    base["projects"] = projects
    base["project"] = fourth
    base["delivery"] = delivery
    return base


def test_the_preview_stops_at_the_cooling_off_tier(api):
    """Both the cooling-off tier and the goodwill tier hold; the preview must report the
    earlier one and the zero retention that goes with it.

    PRD 3.8: "The five tiers are evaluated strictly top to bottom, and the **first** tier
    whose condition holds decides the answer; **no later tier is consulted, ever**."

    Design: Difficulty/combinatorial_formula/cancellation_waiver_ladder_cooling_off_preempts_goodwill
    """
    ctx = _fourth_project_of_a_repeat_household(api)
    customer = get_success_data(
        api.get_customer(ctx["customer"]["id"], PROJECT_COORDINATOR))
    assert customer["project_count"] == 4, (
        "four sales to one household must be visible to the goodwill tier"
    )

    preview = get_success_data(
        api.get_settlement_preview(ctx["project"]["id"],
                                   make_customer_headers(ctx["customer"]["id"]))
    )
    assert_money(preview["deposit_held_cents"], DEPOSIT, "deposit_held_cents")
    # MEASURED forfeits 0.10 of the held deposit: 59002 * 0.10 is 5900.2, which rounds
    # down to 5900; the IN_TRANSIT material costs 0.06 of 250000.
    assert preview["labor_forfeit_pct"] == pytest.approx(0.10, abs=1e-9)
    assert_money(preview["labor_forfeit_cents"], 5900, "labor_forfeit_cents")
    assert_money(preview["restocking_fee_cents"], 15000, "restocking_fee_cents")
    assert_money(preview["gross_retained_cents"], 20900, "gross_retained_cents")

    assert preview["matched_waiver_tier"] == WaiverTier.COOLING_OFF
    assert_money(preview["retained_cents"], 0, "retained_cents")
    assert_money(preview["refund_cents"], DEPOSIT, "refund_cents")
    assert preview["resulting_financial_status"] == FinancialStatus.REFUNDED
    # Half of the gross, 10450, is what the goodwill tier would have retained.
    assert preview["retained_cents"] != 10450, (
        "the goodwill tier must not be consulted once cooling-off has matched"
    )


def test_the_cancellation_refunds_the_whole_deposit_and_returns_the_material(api):
    """The cancellation moves the money exactly as the preview said, and the material in
    transit is turned around in the same request.

    PRD 3.8: "Step seven moves the money: `retained_cents` is added to
    `deposit_forfeited_cents`, `refund_cents` is added to `deposit_refunded_cents`, and
    `deposit_held_cents` is left at zero, which keeps the conservation identity of §2.10
    exactly true."

    Design: Difficulty/combinatorial_formula/cancellation_waiver_ladder_cooling_off_preempts_goodwill
    """
    ctx = _fourth_project_of_a_repeat_household(api)
    project = get_success_data(
        api.cancel_project(ctx["project"]["id"],
                           f.cancel_payload("CUSTOMER_CHANGED_MIND"),
                           make_customer_headers(ctx["customer"]["id"]))
    )

    assert_project_dimensions(project, fulfillment=FulfillmentStatus.CANCELLED,
                              financial=FinancialStatus.REFUNDED,
                              permit=PermitStatus.NOT_REQUIRED)
    assert_instant(project["cancelled_at"], COOLING_OFF_CLOCK, "cancelled_at")
    assert project["cancel_reason"] == "CUSTOMER_CHANGED_MIND"
    assert_deposit_buckets(project, paid=DEPOSIT, held=0, applied=0,
                           refunded=DEPOSIT, forfeited=0)
    # The goodwill split would have left 48552 refunded against 10450 forfeited.
    assert project["deposit_refunded_cents"] != 48552
    assert project["deposit_forfeited_cents"] != 10450

    delivery = fx.read_delivery(api, ctx["delivery"]["id"])
    assert delivery["status"] == DeliveryStatus.RETURNED


# ---------------------------------------------------------------------------
# The four deposit buckets, conserved across cancel and reinstate
# ---------------------------------------------------------------------------
def _scheduled_project_ten_days_on(api):
    """A scheduled project with the material already in transit, cancelled long after
    the cooling-off window has closed, by the household itself."""
    ctx = fx.install_ready(api)
    ctx["assignment"] = fx.hold_assignment(api, ctx["project"]["id"],
                                           ctx["installer"]["id"],
                                           fx.project_version(api,
                                                              ctx["project"]["id"]))
    ctx["delivery"] = fx.move_delivery(api, ctx["delivery"]["id"],
                                       DeliveryStatus.IN_TRANSIT)
    fx.set_clock(api, LATE_CLOCK)
    ctx["project"] = fx.read_project(api, ctx["project"]["id"])
    return ctx


def _cancel_as_household(api, ctx):
    return get_success_data(
        api.cancel_project(ctx["project"]["id"], f.cancel_payload(),
                           make_customer_headers(ctx["customer"]["id"]))
    )


def test_the_cancellation_splits_the_deposit_without_losing_a_cent(api):
    """No waiver tier holds, so the whole gross is retained; the two buckets it lands in
    still sum to the amount the household paid.

    PRD 3.8: "The same project cancelled while `SCHEDULED` with the material
    `IN_TRANSIT`: the labour forfeit is 59002 times 0.25, which is 14750.5 and rounds
    **up** to 14751; the restocking fee is 15000; the gross is 29751; tier five retains
    all of it; the refund is 29251; and the dimension lands in `PARTIALLY_REFUNDED`."

    Design: Difficulty/compensating_invariant/deposit_four_bucket_total_is_conserved_through_cancel_and_reinstate
    """
    ctx = _scheduled_project_ten_days_on(api)
    assert_project_dimensions(ctx["project"],
                              fulfillment=FulfillmentStatus.SCHEDULED,
                              financial=FinancialStatus.DEPOSIT_HELD)

    project = _cancel_as_household(api, ctx)

    assert_deposit_buckets(project, paid=DEPOSIT, held=0, applied=0,
                           refunded=29251, forfeited=29751)
    assert_project_dimensions(project, fulfillment=FulfillmentStatus.CANCELLED,
                              financial=FinancialStatus.PARTIALLY_REFUNDED)
    assert_instant(project["cancelled_at"], LATE_CLOCK, "cancelled_at")

    # The cascade gave the calendar and the warehouse back.
    assignment = fx.read_assignment(api, ctx["assignment"]["id"])
    assert assignment["release_reason"] == ReleaseReason.PROJECT_CANCELLED
    assert_committed_minutes(fx.read_installer(api, ctx["installer"]["id"]), 0)
    assert fx.read_delivery(api, ctx["delivery"]["id"])["status"] == (
        DeliveryStatus.RETURNED
    )


def test_the_reinstatement_puts_both_split_buckets_back_with_no_drift(api):
    """Reinstatement inside the 72-hour window returns the whole of the refunded *and*
    the forfeited bucket to the held bucket, leaving the paid total untouched.

        PRD 3.8: "Reinstatement moves the whole of `deposit_refunded_cents` and
    `deposit_forfeited_cents` back into `deposit_held_cents`, zeroes both,
    leaves `deposit_paid_cents` untouched, and sets `financial_status` to
    `DEPOSIT_HELD`, restoring the pre-cancellation bucket split exactly and
    with no drift — which is why the conservation identity holds before the
    cancellation, after the cancellation and after the reinstatement alike."

    Design: Difficulty/compensating_invariant/deposit_four_bucket_total_is_conserved_through_cancel_and_reinstate
    """
    ctx = _scheduled_project_ten_days_on(api)
    cancelled = _cancel_as_household(api, ctx)

    # 24 hours later, strictly inside the reinstatement window.
    fx.set_clock(api, REINSTATE_CLOCK)
    project = get_success_data(
        api.reinstate_project(cancelled["id"],
                              f.reinstate_payload(cancelled["version"]),
                              PROJECT_COORDINATOR)
    )

    assert_deposit_buckets(project, paid=DEPOSIT, held=DEPOSIT, applied=0,
                           refunded=0, forfeited=0)
    assert_project_dimensions(project, financial=FinancialStatus.DEPOSIT_HELD)
    assert project["cancelled_at"] is None
    assert project["cancel_reason"] is None
    # The frozen quote was never touched by either leg of the round trip.
    assert_money(project["quoted_labor_cents"], QUOTED, "quoted_labor_cents")

    # Money and schedulability come back; history does not.
    assert fx.read_assignment(api, ctx["assignment"]["id"])["status"] == (
        AssignmentStatus.RELEASED
    )
    assert fx.read_delivery(api, ctx["delivery"]["id"])["status"] == (
        DeliveryStatus.RETURNED
    )
