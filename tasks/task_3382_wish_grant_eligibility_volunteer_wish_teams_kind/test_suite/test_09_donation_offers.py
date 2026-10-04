"""Donation offers: valuation variants, the expiry sweep and reservation-time
window guard, depletion at grant completion, reserve/release cycling, and the
quantity conservation invariant.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    abort_plan,
    add_line_item,
    api_client,
    assert_offer_quantities,
    assert_offer_quantity_conservation,
    create_donation_offer,
    create_draft_plan,
    create_line_item_payload,
    get_donation_offer,
    set_clock,
    setup_granted_wish,
    setup_planning_wish,
    submit_plan,
    validate_error,
    validate_paginated,
)

WISH_COORDINATOR = TEST_USERS["wish_coordinator_headers"]
IN_KIND_OFFICER = TEST_USERS["in_kind_officer_headers"]


def test_offer_expiry_window_and_clock_sweep():
    """PRD section 2.5: "Independently of the sweep, an attempt to reserve
    from an offer whose `valid_until` is already in the past at reservation
    time fails with `ERR_DONATION_EXPIRED` (HTTP 409) — the sweep cleans the
    catalogue, but the reservation-time check is the authoritative guard."
    PRD section 2.5: "Advancing the clock triggers an expiry sweep across
    donation offers: any offer still `AVAILABLE`, holding no reserved units,
    whose `valid_until` date falls before the new logical date transitions to
    `EXPIRED` with a version increment."
    PRD section 3.6: "the offer must be `AVAILABLE` (`ERR_INVALID_OFFER_STATE`,
    HTTP 409); the current logical date must not be past the offer's
    `valid_until` (`ERR_DONATION_EXPIRED`)"

    Design: Corner/state_machines/offer_expiry_window_and_clock_sweep
    """
    ctx = setup_planning_wish(wish_type="RECEIVE_ITEM", cash_cost_cents=0)
    plan = ctx["plan"]
    offer = create_donation_offer(quantity_total=4, unit_retail_cents=12000,
                                  valid_from="2026-08-01",
                                  valid_until="2026-08-20")

    expired_window = api_client.create_plan_line_item(
        plan["id"], create_line_item_payload(offer["id"], 1), WISH_COORDINATOR)
    validate_error(expired_window, ApiErrorId.ERR_DONATION_EXPIRED)

    set_clock("2026-09-02T00:00:00Z")
    swept = get_donation_offer(offer["id"])
    assert swept["status"] == "EXPIRED", (
        f"the sweep must mark the unreserved past-window offer EXPIRED, got "
        f"{swept['status']}"
    )

    after_sweep = api_client.create_plan_line_item(
        plan["id"], create_line_item_payload(offer["id"], 1), WISH_COORDINATOR)
    validate_error(after_sweep, ApiErrorId.ERR_INVALID_OFFER_STATE)


def test_offer_depleted_after_full_consumption():
    """PRD section 3.8: "per line the offer's `quantity_reserved` and
    `quantity_total` both fall by the line's quantity — consumption shrinks
    the donation itself, so `quantity_available` does not move — and an offer
    whose total reaches zero becomes `DEPLETED`."

    Design: Corner/state_machines/offer_depleted_after_full_consumption
    """
    ctx = setup_granted_wish(
        wish_type="RECEIVE_ITEM", captured_true_wish="the last toy truck",
        cash_cost_cents=0,
        offer_specs=[{"quantity_total": 1, "quantity": 1,
                      "unit_retail_cents": 12000}])
    offer = get_donation_offer(ctx["offers"][0]["id"])
    assert offer["status"] == "DEPLETED"
    assert_offer_quantities(offer, quantity_total=0, quantity_reserved=0,
                            quantity_available=0)
    assert ctx["wish"]["status"] == "GRANTED"


def test_donation_fmv_retail_basis_full_retail_value():
    """PRD section 3.5: "Under `RETAIL_BASIS`, the unit value is simply the
    full `unit_retail_cents`, and a `partner_declared_unit_cents` supplied
    anyway is ignored."

    Design: Difficulty/dual_variant_calc/donation_fmv_retail_basis_vs_partner_declared
    """
    set_clock()
    offer = create_donation_offer(
        partner_name="SkyWay Airlines", category="AIRLINE",
        valuation_method="RETAIL_BASIS", description="2 round-trip tickets",
        quantity_total=3, unit_retail_cents=50000,
        partner_declared_unit_cents=35000)
    fetched = get_donation_offer(offer["id"])
    assert fetched["fmv_unit_cents"] == 50000, (
        f"RETAIL_BASIS values the unit at full retail (the declared 35000 is "
        f"ignored), got {fetched['fmv_unit_cents']}"
    )


def test_donation_fmv_partner_declared_capped_below_retail():
    """PRD section 3.5: "Under `PARTNER_DECLARED`, the partner's
    `partner_declared_unit_cents` is required — omitting it is a malformed
    request (`ERR_INVALID_REQUEST`) — and the unit value is the lesser of that
    declared figure and a cap computed as 80 percent of `unit_retail_cents`,
    with the cap itself rounded half-up to integer cents before the
    comparison."
    Identical inputs (retail 50000, declared 35000) give min(35000, 40000) ==
    35000 under PARTNER_DECLARED versus 50000 under RETAIL_BASIS.

    Design: Difficulty/dual_variant_calc/donation_fmv_retail_basis_vs_partner_declared
    """
    set_clock()
    retail = create_donation_offer(
        partner_name="SkyWay Airlines", category="AIRLINE",
        valuation_method="RETAIL_BASIS", description="2 round-trip tickets",
        quantity_total=3, unit_retail_cents=50000,
        partner_declared_unit_cents=35000)
    declared = create_donation_offer(
        partner_name="SkyWay Airlines", category="AIRLINE",
        valuation_method="PARTNER_DECLARED",
        description="2 round-trip tickets (declared)", quantity_total=3,
        unit_retail_cents=50000, partner_declared_unit_cents=35000)
    retail_fmv = get_donation_offer(retail["id"])["fmv_unit_cents"]
    declared_fmv = get_donation_offer(declared["id"])["fmv_unit_cents"]
    assert declared_fmv == 35000
    assert retail_fmv == 50000
    assert declared_fmv != retail_fmv, (
        "identical retail/declared inputs must diverge across the two "
        "valuation variants"
    )


def test_offer_fully_reserved_then_reopened_by_abort():
    """PRD section 3.5: "An offer opens in `AVAILABLE` status; when a
    reservation takes the last available unit the offer becomes
    `FULLY_RESERVED`, and when a later release makes availability positive
    again it returns to `AVAILABLE`."
    PRD section 3.6: "From `PENDING_APPROVAL`, aborting moves the plan to
    `CANCELLED`, releases its `RESERVED` lines to `RELEASED` and returns their
    quantities to the offers"

    Design: Difficulty/non_linear_state_machine/donation_offer_reserve_release_reopen_cycle
    """
    ctx = setup_planning_wish(wish_type="RECEIVE_ITEM",
                              captured_true_wish="ten toy trucks",
                              cash_cost_cents=0)
    plan = ctx["plan"]
    offer = create_donation_offer(quantity_total=10, unit_retail_cents=12000)

    add_line_item(plan["id"], offer["id"], 10)
    full = get_donation_offer(offer["id"])
    assert full["status"] == "FULLY_RESERVED"
    assert_offer_quantities(full, quantity_reserved=10, quantity_available=0)

    submit_plan(plan["id"])
    abort_plan(plan["id"])
    reopened = get_donation_offer(offer["id"])
    assert reopened["status"] == "AVAILABLE", (
        f"the abort releases the reservation and reopens the offer, got "
        f"{reopened['status']}"
    )
    assert_offer_quantities(reopened, quantity_total=10, quantity_reserved=0,
                            quantity_available=10)


def test_offer_reopened_units_can_be_reserved_again():
    """PRD section 3.5: "when a later release makes availability positive
    again it returns to `AVAILABLE`" — the same units can then be reserved by
    a replacement plan (AVAILABLE -> FULLY_RESERVED a second time).

    Design: Difficulty/non_linear_state_machine/donation_offer_reserve_release_reopen_cycle
    """
    ctx = setup_planning_wish(wish_type="RECEIVE_ITEM",
                              captured_true_wish="ten toy trucks",
                              cash_cost_cents=0)
    plan1 = ctx["plan"]
    offer = create_donation_offer(quantity_total=10, unit_retail_cents=12000)
    add_line_item(plan1["id"], offer["id"], 10)
    submit_plan(plan1["id"])
    abort_plan(plan1["id"])

    plan2 = create_draft_plan(ctx["wish"]["id"], 0)
    line2 = add_line_item(plan2["id"], offer["id"], 10)
    assert line2["status"] == "RESERVED", (
        "the released units must be reservable by the replacement plan"
    )
    final = get_donation_offer(offer["id"])
    assert final["status"] == "FULLY_RESERVED"
    assert_offer_quantities(final, quantity_reserved=10, quantity_available=0)


def test_quantity_conservation_holds_after_reserve():
    """PRD section 3.5: "`quantity_reserved` starts at 0, and
    `quantity_available` is always `quantity_total` minus `quantity_reserved`."

    Design: Difficulty/compensating_invariant/donation_quantity_reserve_release_conservation
    """
    ctx = setup_planning_wish(wish_type="RECEIVE_ITEM",
                              captured_true_wish="three toy trucks",
                              cash_cost_cents=0)
    plan = ctx["plan"]
    offer = create_donation_offer(quantity_total=10, unit_retail_cents=12000)
    add_line_item(plan["id"], offer["id"], 3)

    after = get_donation_offer(offer["id"])
    assert_offer_quantities(after, quantity_total=10, quantity_reserved=3,
                            quantity_available=7)
    assert_offer_quantity_conservation(after)


def test_quantity_conservation_restored_exactly_after_abort():
    """PRD section 3.6: "From `PENDING_APPROVAL`, aborting moves the plan to
    `CANCELLED`, releases its `RESERVED` lines to `RELEASED` and returns their
    quantities to the offers" — the compensating release restores the exact
    pre-reserve quantities with no drift.

    Design: Difficulty/compensating_invariant/donation_quantity_reserve_release_conservation
    """
    ctx = setup_planning_wish(wish_type="RECEIVE_ITEM",
                              captured_true_wish="three toy trucks",
                              cash_cost_cents=0)
    plan = ctx["plan"]
    offer = create_donation_offer(quantity_total=10, unit_retail_cents=12000)
    line = add_line_item(plan["id"], offer["id"], 3)
    submit_plan(plan["id"])
    abort_plan(plan["id"])

    restored = get_donation_offer(offer["id"])
    assert_offer_quantities(restored, quantity_total=10, quantity_reserved=0,
                            quantity_available=10)
    assert_offer_quantity_conservation(restored)
    assert restored["status"] == "AVAILABLE"

    lines_resp = api_client.list_plan_line_items(plan["id"], WISH_COORDINATOR)
    items, _ = validate_paginated(lines_resp)
    released = [item for item in items if item["id"] == line["id"]]
    assert released and released[0]["status"] == "RELEASED"
