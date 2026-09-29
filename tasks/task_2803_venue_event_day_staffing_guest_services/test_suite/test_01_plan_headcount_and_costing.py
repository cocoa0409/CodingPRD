"""Block sizing per plan variant and the pinned six-step costing pass."""

from test_helpers import (
    assert_cents,
    assert_fields,
    create_elevator_operator,
    create_event,
    create_guest_services_rep,
    create_plan,
    create_slot,
    create_ticket_taker,
    create_usher,
    read_event,
    read_plan,
    read_slot,
    set_clock,
)

USHER_WINDOW = ("2026-09-12T16:00:00Z", "2026-09-12T22:00:00Z")


def _event_with_both_bases(client):
    """One event carrying both a forecast of 40000 and a historical count of 25000."""
    set_clock(client, "2026-09-01T09:00:00Z")
    event = create_event(
        client,
        name="Season Opener",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=40000,
        historical_actual_attendance=25000,
    )
    usher = create_usher(
        client,
        base_hourly_rate_cents=2200,
        attendance_ratio_per_1000=1.5,
        min_headcount=4,
        required_certifications=["EVACUATION_PROCEDURES"],
    )
    forecast_plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    historical_plan = create_plan(client, event["id"], plan_variant="HISTORICAL_ACTUAL")
    shift_start, shift_end = USHER_WINDOW
    forecast_slot = create_slot(
        client,
        forecast_plan["id"],
        usher["id"],
        zone_code="Z100",
        shift_start=shift_start,
        shift_end=shift_end,
    )
    historical_slot = create_slot(
        client,
        historical_plan["id"],
        usher["id"],
        zone_code="Z100",
        shift_start=shift_start,
        shift_end=shift_end,
    )
    return {
        "event": event,
        "usher": usher,
        "forecast_plan": forecast_plan,
        "historical_plan": historical_plan,
        "forecast_slot": forecast_slot,
        "historical_slot": historical_slot,
    }


def test_each_plan_variant_reselects_its_own_basis_and_multiplier(client):
    """Byte-identical blocks diverge by 40 heads because their plans read different bases.

    "Consider an event forecasting 40000 with a historical count of 25000 and an
    usher family whose ratio is 1.5 heads per thousand attendees: the
    forecast-based plan works from 40000 at `TIER_4` and 1.45, giving an usher
    block 87 heads, while the historical plan works from 25000 at `TIER_3` and
    1.25, giving the same block 47."

    Design: Difficulty/dual_variant_calc/headcount_variant_forecast_vs_historical
    """
    context = _event_with_both_bases(client)

    assert_fields(read_event(client, context["event"]["id"]), attendance_tier="TIER_4")
    assert_fields(
        read_plan(client, context["forecast_plan"]["id"]),
        basis_attendance=40000,
        basis_attendance_tier="TIER_4",
    )
    assert_fields(
        read_plan(client, context["historical_plan"]["id"]),
        basis_attendance=25000,
        basis_attendance_tier="TIER_3",
    )

    forecast_slot = read_slot(client, context["forecast_slot"]["id"])
    historical_slot = read_slot(client, context["historical_slot"]["id"])
    assert_fields(
        forecast_slot,
        ratio_derived_headcount=87,
        required_headcount=87,
        shift_minutes=360,
    )
    assert_fields(
        historical_slot,
        ratio_derived_headcount=47,
        required_headcount=47,
        shift_minutes=360,
    )
    assert forecast_slot["required_headcount"] - historical_slot["required_headcount"] == 40, (
        "the two variants must differ by exactly 40 heads on identical block input"
    )


def test_the_variant_divergence_propagates_into_cents_and_the_surcharge_tier(client):
    """The 40-head gap moves both plans' money and flips the surcharge tier on and off.

    "The two variants differ only in which attendance number becomes the plan's
    `basis_attendance`, but that difference propagates through every headcount and
    every cent."

    Design: Difficulty/dual_variant_calc/headcount_variant_forecast_vs_historical
    """
    context = _event_with_both_bases(client)

    forecast_slot = read_slot(client, context["forecast_slot"]["id"])
    historical_slot = read_slot(client, context["historical_slot"]["id"])
    assert_cents(forecast_slot["slot_labor_cost_cents"], 1148400, "forecast slot cost")
    assert_cents(historical_slot["slot_labor_cost_cents"], 620400, "historical slot cost")

    forecast_plan = read_plan(client, context["forecast_plan"]["id"])
    assert_fields(forecast_plan, total_required_headcount=87)
    assert_cents(forecast_plan["base_labor_cost_cents"], 1148400, "forecast base")
    assert_cents(forecast_plan["accessibility_surcharge_cents"], 40194, "forecast surcharge")
    assert_cents(forecast_plan["projected_labor_cost_cents"], 1188594, "forecast projected")

    historical_plan = read_plan(client, context["historical_plan"]["id"])
    assert_fields(historical_plan, total_required_headcount=47)
    assert_cents(historical_plan["base_labor_cost_cents"], 620400, "historical base")
    assert_cents(
        historical_plan["accessibility_surcharge_cents"], 0, "historical surcharge"
    )
    assert_cents(
        historical_plan["projected_labor_cost_cents"], 620400, "historical projected"
    )


def _two_odd_length_blocks(client):
    """One plan carrying a 245-minute block, ready for a 125-minute sibling."""
    set_clock(client, "2026-09-02T09:00:00Z")
    event = create_event(
        client,
        name="Precision Fixture",
        doors_open_at="2026-09-12T16:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=6000,
    )
    ticket_taker = create_ticket_taker(
        client,
        base_hourly_rate_cents=2000,
        attendance_ratio_per_1000=0.8,
        min_headcount=3,
        required_certifications=[],
    )
    plan = create_plan(client, event["id"])
    first = create_slot(
        client,
        plan["id"],
        ticket_taker["id"],
        zone_code="Z120",
        shift_start="2026-09-12T16:00:00Z",
        shift_end="2026-09-12T20:05:00Z",
    )
    return {"event": event, "plan": plan, "position_type": ticket_taker, "first": first}


def test_block_costs_are_rounded_once_each_before_they_are_summed(client):
    """Two blocks of 40833.3333 and 20833.3333 cents must total 61666, not 61667.

    "Step two sums those already-rounded per-block figures into
    `base_labor_cost_cents`; the exact products are never summed."

    Design: Difficulty/combinatorial_formula/plan_cost_round_per_slot_then_sum
    """
    context = _two_odd_length_blocks(client)

    second = create_slot(
        client,
        context["plan"]["id"],
        context["position_type"]["id"],
        zone_code="Z121",
        shift_start="2026-09-12T20:35:00Z",
        shift_end="2026-09-12T22:40:00Z",
    )

    assert_fields(
        read_plan(client, context["plan"]["id"]),
        basis_attendance=6000,
        basis_attendance_tier="TIER_1",
    )
    first = read_slot(client, context["first"]["id"])
    assert_fields(first, shift_minutes=245, required_headcount=5, ratio_derived_headcount=5)
    assert_fields(second, shift_minutes=125, required_headcount=5, ratio_derived_headcount=5)
    assert_cents(first["slot_labor_cost_cents"], 40833, "245-minute block cost")
    assert_cents(second["slot_labor_cost_cents"], 20833, "125-minute block cost")

    plan = read_plan(client, context["plan"]["id"])
    assert_cents(plan["base_labor_cost_cents"], 61666, "base_labor_cost_cents")
    assert plan["base_labor_cost_cents"] != 61667, (
        "rounding the exact sum 61666.6667 once would give 61667, which is incorrect"
    )


def test_a_plan_under_sixty_heads_draws_no_accessibility_surcharge(client):
    """Ten heads sit below the lowest surcharge floor, so the projection equals the base.

    "Step four selects an accessibility surcharge rate from that plan-level
    headcount total and never from an individual block: a total of 300 heads or
    more draws 900 basis points, at least 150 but fewer than 300 draws 600 basis
    points, at least 60 but fewer than 150 draws 350 basis points, and anything
    below 60 draws nothing."

    Design: Difficulty/combinatorial_formula/plan_cost_round_per_slot_then_sum
    """
    context = _two_odd_length_blocks(client)

    create_slot(
        client,
        context["plan"]["id"],
        context["position_type"]["id"],
        zone_code="Z121",
        shift_start="2026-09-12T20:35:00Z",
        shift_end="2026-09-12T22:40:00Z",
    )

    plan = read_plan(client, context["plan"]["id"])
    assert_fields(plan, total_required_headcount=10)
    assert_cents(plan["accessibility_surcharge_cents"], 0, "accessibility_surcharge_cents")
    assert_cents(plan["projected_labor_cost_cents"], 61666, "projected_labor_cost_cents")


def _plan_at_one_hundred_forty_six_heads(client):
    """Three families on one plan totalling 146 heads, one family short of the 600 bp tier."""
    set_clock(client, "2026-09-03T09:00:00Z")
    event = create_event(
        client,
        name="Surcharge Order Fixture",
        doors_open_at="2026-09-12T16:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=40000,
    )
    usher = create_usher(
        client,
        base_hourly_rate_cents=2200,
        attendance_ratio_per_1000=1.5,
        min_headcount=4,
        required_certifications=["EVACUATION_PROCEDURES"],
    )
    ticket_taker = create_ticket_taker(
        client,
        base_hourly_rate_cents=2000,
        attendance_ratio_per_1000=0.8,
        min_headcount=3,
        required_certifications=[],
    )
    elevator = create_elevator_operator(
        client,
        base_hourly_rate_cents=2600,
        attendance_ratio_per_1000=0.2,
        min_headcount=2,
        required_certifications=["ELEVATOR_OPERATION", "EVACUATION_PROCEDURES"],
    )
    rep = create_guest_services_rep(
        client,
        base_hourly_rate_cents=2400,
        attendance_ratio_per_1000=0.35,
        min_headcount=2,
        required_certifications=["CODE_OF_CONDUCT"],
        is_tip_eligible=True,
        is_contracted_position=True,
    )
    plan = create_plan(client, event["id"])
    usher_slot = create_slot(
        client,
        plan["id"],
        usher["id"],
        zone_code="Z130",
        shift_start="2026-09-12T16:00:00Z",
        shift_end="2026-09-12T22:00:00Z",
    )
    ticket_slot = create_slot(
        client,
        plan["id"],
        ticket_taker["id"],
        zone_code="Z131",
        shift_start="2026-09-12T16:05:00Z",
        shift_end="2026-09-12T22:00:00Z",
    )
    elevator_slot = create_slot(
        client,
        plan["id"],
        elevator["id"],
        zone_code="Z132",
        shift_start="2026-09-12T17:00:00Z",
        shift_end="2026-09-12T22:00:00Z",
    )
    return {
        "event": event,
        "plan": plan,
        "rep": rep,
        "usher_slot": usher_slot,
        "ticket_slot": ticket_slot,
        "elevator_slot": elevator_slot,
    }


def _add_rep_block(client, context):
    return create_slot(
        client,
        context["plan"]["id"],
        context["rep"]["id"],
        zone_code="Z133",
        shift_start="2026-09-12T16:00:00Z",
        shift_end="2026-09-12T22:00:00Z",
    )


def test_the_surcharge_rate_is_selected_from_the_plan_level_headcount_total(client):
    """A fourth family lifts the total past 150 heads and flips 350 bp to 600 bp.

    "Step five computes `accessibility_surcharge_cents` as `base_labor_cost_cents`
    multiplied by that basis-point rate divided by 10000, rounded half up to whole
    cents."

    Design: Difficulty/combinatorial_formula/plan_surcharge_tier_evaluation_order
    """
    context = _plan_at_one_hundred_forty_six_heads(client)

    before = read_plan(client, context["plan"]["id"])
    assert_fields(before, total_required_headcount=146)
    assert_cents(before["base_labor_cost_cents"], 1860567, "base before the fourth family")
    assert_cents(before["accessibility_surcharge_cents"], 65120, "350 bp surcharge")
    assert_cents(before["projected_labor_cost_cents"], 1925687, "projection at 350 bp")

    rep_slot = _add_rep_block(client, context)
    assert_fields(rep_slot, required_headcount=21)
    assert_cents(rep_slot["slot_labor_cost_cents"], 302400, "guest services block cost")

    after = read_plan(client, context["plan"]["id"])
    assert_fields(after, total_required_headcount=167)
    assert_cents(after["base_labor_cost_cents"], 2162967, "base after the fourth family")
    assert_cents(after["accessibility_surcharge_cents"], 129778, "600 bp surcharge")
    assert after["accessibility_surcharge_cents"] != 40194, (
        "choosing the rate per block instead of per plan would give 40194"
    )


def test_the_surcharge_never_re_enters_the_base_or_the_headcount_total(client):
    """The sixth step only adds: it feeds nothing back into the earlier five.

    "Step six adds the two together into `projected_labor_cost_cents`; the
    surcharge never re-enters the headcount total or the surcharge-tier selection."

    Design: Difficulty/combinatorial_formula/plan_surcharge_tier_evaluation_order
    """
    context = _plan_at_one_hundred_forty_six_heads(client)

    assert_cents(
        read_slot(client, context["usher_slot"]["id"])["slot_labor_cost_cents"],
        1148400,
        "usher block cost",
    )
    assert_cents(
        read_slot(client, context["ticket_slot"]["id"])["slot_labor_cost_cents"],
        556167,
        "ticket taker block cost",
    )
    assert_cents(
        read_slot(client, context["elevator_slot"]["id"])["slot_labor_cost_cents"],
        156000,
        "elevator operator block cost",
    )

    _add_rep_block(client, context)

    plan = read_plan(client, context["plan"]["id"])
    assert_fields(plan, total_required_headcount=167)
    assert_cents(plan["base_labor_cost_cents"], 2162967, "base_labor_cost_cents")
    assert (
        plan["projected_labor_cost_cents"]
        == plan["base_labor_cost_cents"] + plan["accessibility_surcharge_cents"]
    ), "the projection is exactly the base plus the surcharge"
    assert_cents(plan["projected_labor_cost_cents"], 2292745, "projected_labor_cost_cents")
