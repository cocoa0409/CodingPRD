"""Delivery outcomes, the per-line chargeback and the no-show contagion chain."""

import pytest

from test_helpers import (
    ADMIN,
    DISPATCH,
    WAREHOUSE,
    ApiErrorId,
    allocate,
    create_referral,
    create_truck,
    create_volunteer,
    donation_item_payload,
    drive_stop_outcome,
    get_run,
    get_stop,
    issue_voucher,
    list_waitlist,
    record_outcome,
    set_clock,
    setup_agency_and_household,
    setup_allocated_voucher,
    setup_crewed_run,
    setup_dispatched_run,
    submit_referral,
    supply_clean_stock,
    validate_error,
    validate_paginated,
    validate_success,
    voucher_line_payload,
)
from test_helpers.assertions import assert_delivery_stop
from test_helpers.fixtures import create_approved_referral


def _two_line_no_show_scenario():
    """A TABLE_SET and a DRESSER fully allocated, delivered out and missed."""
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("TABLE_SET", 1, "B"),
               voucher_line_payload("DRESSER", 1, "B")],
        categories=["TABLE_SET", "DRESSER"],
        offer_items=[donation_item_payload("TABLE_SET", "B", False, 25.0),
                     donation_item_payload("DRESSER", "B", False, 15.0)],
        truck_label="BOX-3", agency_name="Midtown Care Network",
    )
    booked = setup_dispatched_run(scenario["truck"]["id"], scenario["voucher"]["id"],
                                  county="CENTRAL", volunteer_name="Ray Osei")
    scenario.update(booked)
    scenario["outcome"] = record_outcome(booked["stop"]["id"], "NO_SHOW")
    return scenario


def _double_no_show_scenario():
    """One household misses two consecutive deliveries while holding a second
    SUBMITTED referral and a WAITING waitlist entry."""
    set_clock("2026-08-04T09:00:00Z")
    base = setup_agency_and_household(
        agency_county="CENTRAL", quota=5, household_size=4,
        client_county="CENTRAL", agency_name="Foxglove Community Aid",
    )
    agency_id = base["agency"]["id"]
    client_id = base["client"]["id"]

    referral_a = create_approved_referral(agency_id, client_id,
                                          requested_categories=["BED"])
    voucher = issue_voucher(agency_id, referral_a["id"],
                            [voucher_line_payload("BED", 2, "B")])
    truck = create_truck(label="BOX-6", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)
    supply_clean_stock(
        truck["id"], [donation_item_payload("BED", "B", False, 30.0)],
        donor_name="Nils Bergstrom", donor_phone="555-0188",
    )
    allocate(voucher["id"], voucher["version"])
    waitlist_entry = list_waitlist(client_id=client_id, status="WAITING")[0]

    referral_b = create_referral(agency_id, client_id,
                                 requested_categories=["DRESSER"])
    submit_referral(referral_b["id"], agency_id)

    volunteer = create_volunteer(name="Tova Klein", county="CENTRAL",
                                 lift_certified=True)
    first = drive_stop_outcome(
        truck["id"], voucher["id"], "NO_SHOW",
        "2026-08-05", "2026-08-05T09:00:00Z", "2026-08-05T17:00:00Z",
        volunteer=volunteer,
    )
    second_booking = setup_dispatched_run(
        truck["id"], voucher["id"], service_date="2026-08-06",
        window_start="2026-08-06T09:00:00Z", window_end="2026-08-06T17:00:00Z",
        county="CENTRAL", volunteer=volunteer,
    )
    second_outcome = record_outcome(second_booking["stop"]["id"], "NO_SHOW")

    return {
        "agency": base["agency"], "client": base["client"],
        "referral_a": referral_a, "referral_b": referral_b, "voucher": voucher,
        "truck": truck, "waitlist_entry": waitlist_entry, "volunteer": volunteer,
        "first": first, "second_booking": second_booking,
        "second_outcome": second_outcome,
    }


# ─── Corner: the outcome state gate ────────────────────────────────────

def test_recording_an_outcome_before_dispatch_is_refused(api):
    """PRD §3.8: "Every outcome requires the stop to be in `SCHEDULED` and its
    run to be in `DISPATCHED`; anything else is rejected with
    `ERR_STOP_INVALID_STATE`."
    PRD §3.8: "**A successful delivery** moves the stop `SCHEDULED → DELIVERED`
    and leaves its `chargeback_cents` at 0. Every inventory unit held for that
    voucher moves `STAGED → DELIVERED`, bumping each unit's `version`."

    Design: Corner/state_machines/corner_stop_outcome_before_run_dispatch_rejected
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("BED", 1, "B")],
        offer_items=[donation_item_payload("BED", "B", False, 30.0)],
        truck_label="BOX-25", agency_name="Norwood Family Fund",
    )
    booked = setup_crewed_run(scenario["truck"]["id"], scenario["voucher"]["id"],
                              volunteer_name="Rosa Iglesias")
    assert booked["run"]["status"] == "CREWED", "the run is deliberately not dispatched"

    response = api.record_stop_outcome(
        booked["stop"]["id"], {"outcome": "DELIVERED"}, DISPATCH
    )
    validate_error(response, ApiErrorId.ERR_STOP_INVALID_STATE.value, 409)

    stop_now = get_stop(booked["run"]["id"], booked["stop"]["id"])
    assert stop_now["status"] == "SCHEDULED"
    assert get_run(booked["run"]["id"])["status"] == "CREWED"

    voucher_now = validate_success(api.get_voucher(scenario["voucher"]["id"], ADMIN))
    assert voucher_now["status"] == "SCHEDULED"

    household = validate_success(api.get_client(scenario["client"]["id"], ADMIN))
    assert household["lifetime_vouchers_delivered"] == 0

    reserved, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "RESERVED", "limit": 100})
    )
    assert len(reserved) == 1, "the stock never reached the DELIVERED state"


# ─── Difficulty: the chargeback rounds per line before summing ─────────

def test_chargeback_rounds_each_line_before_the_lines_are_summed(api):
    """PRD §3.8: "Walking those lines in ascending `created_at` order, each
    line's charge is its category's base amount multiplied by its
    `quantity_allocated` — read as it stood *before* this request touched any
    stock — multiplied by the rate, and that product is rounded half up to whole
    cents *at the line*."
    PRD §3.8: "The category base amounts are 2500 cents for `BED`, 3000 for
    `SOFA`, 1500 for `CRIB`, 1150 for `TABLE_SET`, 950 for `DRESSER`, 650 for
    `KITCHEN_KIT` and 250 for `LINENS`. The stop's `chargeback_cents` is then
    the sum of those already-rounded line charges, and that same total is added
    to the `no_show_credits_owed_cents` of the agency reached from the stop
    through its voucher and that voucher's referral."
    PRD §2.7: "In the no-show chargeback, rounding is applied once per voucher
    line, before the line charges are summed. Summing unrounded line charges and
    rounding the total once is wrong and will differ by a cent or more."

    Design: Difficulty/combinatorial_formula/chargeback_rounds_per_line_before_summing
    """
    scenario = _two_line_no_show_scenario()

    assert scenario["allocated"]["client_due_cents"] == 1260, (
        "CENTRAL 3000 plus one bulk increment of 1200 with no lift surcharge, "
        "70 percent subsidised"
    )

    stop = scenario["outcome"]
    assert_delivery_stop(stop)
    assert stop["chargeback_cents"] == 946, (
        "TABLE_SET 517.5 rounds to 518 and DRESSER 427.5 rounds to 428"
    )
    assert stop["status"] == "NO_SHOW"

    agency_now = validate_success(api.get_agency(scenario["agency"]["id"], ADMIN))
    assert agency_now["no_show_credits_owed_cents"] == 946, (
        "the same already-rounded total lands on the agency ledger"
    )


def test_no_show_parks_the_stock_and_hands_the_voucher_back_allocated(api):
    """PRD §3.8: "**A no-show** — nobody home — moves the stop `SCHEDULED →
    NO_SHOW` and bills the agency. Every staged unit reverts `STAGED →
    RESERVED`, keeping its `reserved_for_voucher_line_id` and leaving the line's
    `quantity_allocated` untouched, and its `available_since` is deliberately
    **not** restamped: the furniture rides back to the warehouse still earmarked
    for that household."
    PRD §3.8: "In all three cases the run's `stop_count` drops by 1, and when
    the stop just closed was the run's last `SCHEDULED` stop the run moves
    `DISPATCHED → COMPLETED` automatically, bumping the run's `version`."
    PRD §3.1: "If fewer than two stops are in the window, `standing` is `GOOD`."

    Design: Difficulty/combinatorial_formula/chargeback_rounds_per_line_before_summing
    """
    scenario = _two_line_no_show_scenario()

    voucher_now = validate_success(api.get_voucher(scenario["voucher"]["id"], ADMIN))
    assert voucher_now["status"] == "ALLOCATED", (
        "every line is still fully filled, so the voucher goes back to ALLOCATED"
    )

    household = validate_success(api.get_client(scenario["client"]["id"], ADMIN))
    assert household["no_show_strikes"] == 1
    assert household["status"] == "ACTIVE", "one strike is below the ban threshold"

    agency_now = validate_success(api.get_agency(scenario["agency"]["id"], ADMIN))
    assert agency_now["standing"] == "GOOD", "a single terminal stop cannot suspend"

    assert get_run(scenario["run"]["id"])["status"] == "COMPLETED"

    reserved, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "RESERVED", "limit": 100})
    )
    assert len(reserved) == 2, "both units stay earmarked for the household"
    staged, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "STAGED", "limit": 100})
    )
    assert staged == []


# ─── Difficulty: the second no-show fires the contagion chain ──────────

def test_second_no_show_puts_the_household_on_hold_under_a_ninety_day_ban(api):
    """PRD §3.8: "**The no-show contagion chain.** A no-show — and only a
    no-show — fires a cascade in this order. Step one raises the household's
    `no_show_strikes` by 1. Step two fires only when that raised count reaches
    2: the household's `status` becomes `ON_HOLD` and its `delivery_ban_until`
    is set to the current instant plus 90 days."
    PRD §3.1: "Otherwise the system takes the count of `NO_SHOW` stops in the
    window divided by the total count of stops in the window, as an exact
    rational value with no rounding, and sets `standing` to `SUSPENDED` when
    that share is at least one half, otherwise to `PROBATION` when it is at
    least one quarter, otherwise to `GOOD`."

    Design: Difficulty/transitive_cascade/second_no_show_cascades_hold_denial_and_waitlist_cancel
    """
    scenario = _double_no_show_scenario()

    assert scenario["first"]["outcome"]["chargeback_cents"] == 1125, (
        "BED 2500 cents times one allocated unit at the 0.45 no-show rate"
    )
    assert scenario["second_outcome"]["chargeback_cents"] == 1125

    household = validate_success(api.get_client(scenario["client"]["id"], ADMIN))
    assert household["no_show_strikes"] == 2
    assert household["status"] == "ON_HOLD"
    assert household["delivery_ban_until"] == "2026-11-02T09:00:00.000Z"

    agency_now = validate_success(api.get_agency(scenario["agency"]["id"], ADMIN))
    assert agency_now["no_show_credits_owed_cents"] == 2250
    assert agency_now["standing"] == "SUSPENDED", "both terminal stops are no-shows"

    assert get_run(scenario["second_booking"]["run"]["id"])["status"] == "COMPLETED"


def test_on_hold_household_has_its_referral_denied_and_waitlist_cancelled(api):
    """PRD §3.8: "Step three fires only because the household has just gone
    `ON_HOLD`: every referral of that household in `SUBMITTED` or `RETURNED` is
    denied with the auto-denial note described in §3.2, and every `WAITING`
    waitlist entry of that household moves to `CANCELLED`."
    PRD §3.2: "When a household is placed `ON_HOLD` by the no-show contagion
    described in §3.8, every referral of that household sitting in `SUBMITTED`
    moves `SUBMITTED → DENIED`, and every referral sitting in `RETURNED` moves
    `RETURNED → DENIED`."

    Design: Difficulty/transitive_cascade/second_no_show_cascades_hold_denial_and_waitlist_cancel
    """
    scenario = _double_no_show_scenario()

    referral_b_now = validate_success(
        api.get_referral(scenario["referral_b"]["id"], ADMIN)
    )
    assert referral_b_now["status"] == "DENIED", (
        "the SUBMITTED referral of the on-hold household is auto-denied"
    )

    referral_a_now = validate_success(
        api.get_referral(scenario["referral_a"]["id"], ADMIN)
    )
    assert referral_a_now["status"] == "APPROVED", (
        "the approved referral behind the voucher is not part of the denial sweep"
    )

    entry_now = validate_success(
        api.get_waitlist_entry(scenario["waitlist_entry"]["id"], ADMIN)
    )
    assert entry_now["status"] == "CANCELLED"

    voucher_now = validate_success(api.get_voucher(scenario["voucher"]["id"], ADMIN))
    assert voucher_now["status"] == "PARTIALLY_ALLOCATED", (
        "one of the two requested BEDs is still short"
    )
    assert voucher_now["fill_ratio"] == pytest.approx(0.5, abs=0.0005)
