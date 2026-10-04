"""Feeding service cost accumulation and the dual-variant shelter operating cost."""
from test_helpers import (
    approve_assistance,
    create_client,
    open_case,
    register_client,
    setup_open_shelter,
    submit_assistance_request,
    validate_success,
    verify_case_eligibility,
)


def _feeding_event(api, bundle, meal_type, served_at):
    return validate_success(api.record_feeding_service(
        bundle["shelter_id"],
        {"meal_type": meal_type, "served_at": served_at,
         "meals_planned": 60, "meals_served": 41, "unit_cost_cents": 100},
        bundle["manager_headers"]), 201)


def _cost_scenario(api):
    """Shelter with two feeding events, an arrived AIR deployment and one approved award."""
    bundle = setup_open_shelter()
    _feeding_event(api, bundle, "DINNER", "2026-09-03T18:00:00Z")
    _feeding_event(api, bundle, "BREAKFAST", "2026-09-04T07:00:00Z")

    client = create_client(bundle["region_id"])
    register_client(bundle["shelter_id"], client["id"], bundle["manager_headers"])

    pool = validate_success(api.create_fund_pool(
        {"fund_code": "DR-9101-GEN", "restriction_type": "UNRESTRICTED",
         "region_id": bundle["region_id"], "total_received_cents": 500000},
        bundle["finance_headers"]), 201)

    case = open_case(client["id"], bundle["operation_id"])
    case = verify_case_eligibility(case["id"])
    request = submit_assistance_request(
        case["id"], pool["id"], assistance_type="HOUSING", requested_amount_cents=50000)
    # Approval is a two-step operation (PRD §3.7): the first call only verifies
    # eligibility, and it is the second that leaves the request APPROVED. The
    # PROVISIONAL cost only counts money actually promised (APPROVED/CARD_ISSUED).
    approve_assistance(request["id"])
    approve_assistance(request["id"])

    bundle.update({"client": client, "pool": pool, "case": case, "request": request})
    return bundle


def test_provisional_operating_cost_rolls_up_planned_meals_travel_and_promised_aid(api):
    """PRD §3.3: "Under `PROVISIONAL`, the direct cost is the sum of three components. The first
    is, for every feeding-service event recorded on this shelter, the `meals_planned` for that
    event multiplied by its `unit_cost_cents` and then by 10,625 and divided by 10,000."

    PRD §3.3: "The `operational_cost_cents` field is recomputed whenever the shelter is read, and
    the `reporting_mode` value selects which variant is returned."

    Design: Difficulty/dual_variant_calc/shelter_cost_provisional_vs_final
    """
    bundle = _cost_scenario(api)

    shelter = validate_success(api.get_shelter_operation(
        bundle["shelter_id"], bundle["coordinator_headers"],
        params={"reporting_mode": "PROVISIONAL"}))

    assert shelter["operational_cost_cents"] == 115831


def test_final_operating_cost_rolls_up_served_meals_completed_travel_and_paid_aid(api):
    """PRD §3.3: "Under `FINAL`, the direct cost is the sum of three different components. The
    first is the shelter's accumulated `feeding_cost_cents`, which is already built from per-line
    rounded amounts."

    PRD §3.3: "Both variants build a direct cost and then add overhead, and both compute
    overhead identically: take the direct cost, multiply it by 750 and divide by 10,000, round
    that half up to a whole number of cents, and use whichever is larger between that result and
    2,500 cents."

    Design: Difficulty/dual_variant_calc/shelter_cost_provisional_vs_final
    """
    bundle = _cost_scenario(api)

    shelter = validate_success(api.get_shelter_operation(
        bundle["shelter_id"], bundle["coordinator_headers"],
        params={"reporting_mode": "FINAL"}))

    assert shelter["operational_cost_cents"] == 11212


def test_feeding_line_cost_rounds_before_accumulating(api):
    """PRD §3.3: "the raw line cost is `meals_served` multiplied by `unit_cost_cents`, then
    multiplied by 10,625 and divided by 10,000 ... and that raw figure is rounded half up to a
    whole number of cents."

    Design: Difficulty/combinatorial_formula/feeding_cost_per_line_rounding_order
    """
    bundle = setup_open_shelter()

    first = _feeding_event(api, bundle, "DINNER", "2026-09-03T18:00:00Z")
    assert first["feeding_cost_cents"] == 4356

    second = _feeding_event(api, bundle, "BREAKFAST", "2026-09-04T07:00:00Z")
    assert second["feeding_cost_cents"] == 8712, (
        "each line is rounded before accumulation, not summed raw and rounded once")
    assert second["meals_served_total"] == 82


def test_feeding_cost_accumulates_rounded_lines_not_raw_lines(api):
    """PRD §3.3: "Rounding each line before accumulating is mandatory: summing the raw unrounded
    line costs and rounding once at the end produces a different total for identical events and
    is not the specified behavior."

    Design: Difficulty/combinatorial_formula/feeding_cost_per_line_rounding_order
    """
    bundle = setup_open_shelter()

    _feeding_event(api, bundle, "DINNER", "2026-09-03T18:00:00Z")
    _feeding_event(api, bundle, "BREAKFAST", "2026-09-04T07:00:00Z")
    _feeding_event(api, bundle, "LUNCH", "2026-09-04T12:00:00Z")

    shelter = validate_success(
        api.get_shelter_operation(bundle["shelter_id"], bundle["manager_headers"]))
    assert shelter["feeding_cost_cents"] == 4356 * 3
    assert shelter["feeding_cost_cents"] != 13069, (
        "13069 is the sum-then-round-once result for three identical lines")
    assert shelter["meals_served_total"] == 123
