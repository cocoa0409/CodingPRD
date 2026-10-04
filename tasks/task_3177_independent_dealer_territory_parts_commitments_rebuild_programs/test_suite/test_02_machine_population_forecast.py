"""Machine population, coverage multipliers and the parts demand forecast."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    approve_equipment_financing,
    create_dealer,
    create_equipment_order,
    create_population_record,
    create_support_agreement,
    get_forecast,
    get_population_record,
    parts_manager_headers,
    retire_population_record,
    set_clock,
    submit_equipment_order,
)


def _dealer(territory_code="T-410", legal_name="High Plains Machinery Co"):
    set_clock()
    return create_dealer(legal_name=legal_name, territory_code=territory_code)


def test_forecast_rounds_each_record_up_then_sums():
    """PRD §2.9: "The canonical dealer forecast, served by `GET
    /dealer-network/machine-population-records/forecast` for a supplied
    `dealer_id`, is the `per_record_ceiling` variant: each `ACTIVE` record's
    product is rounded up to the next whole unit individually and the rounded
    values are then summed, with no further rounding." PRD §2.9: "it sums the per-record products exactly and rounds the total up once." PRD §2.9: "A
    population record's `projected_annual_parts_units` is the family base demand
    multiplied by the serial's coverage multiplier and then by the weight class
    multiplier, with the product rounded up to the next whole unit."

    Design: Difficulty/combinatorial_formula/forecast_parts_demand_per_record_ceiling_vs_sum_then_ceiling
    """
    dealer = _dealer()
    create_population_record(dealer, "SN-3002", product_family="EXCAVATION",
                             machine_operating_weight_lb=50000)
    create_population_record(dealer, "SN-3003", product_family="EARTHMOVING",
                             machine_operating_weight_lb=120000)
    create_population_record(dealer, "SN-3004", product_family="COMPACTION",
                             machine_operating_weight_lb=50000)
    create_population_record(dealer, "SN-3005", product_family="COMPACTION",
                             machine_operating_weight_lb=50000)
    create_population_record(dealer, "SN-3001", product_family="LIFT_TRUCK",
                             machine_operating_weight_lb=30000)
    create_support_agreement(dealer, "SN-3001", plan_tier="PREMIUM")
    create_support_agreement(dealer, "SN-3002", plan_tier="PLUS")

    # PRD §2.9: per-record ceilings are 36*1.5*0.8 -> 44 (LIFT_TRUCK, PREMIUM,
    # LIGHT), 40*1.25 -> 50 (EXCAVATION, PLUS, MIDDLE), 48*1.2 -> 58
    # (EARTHMOVING, HEAVY) and 28 each for the two COMPACTION rows.
    data = get_forecast(dealer["id"])
    assert data["forecast_parts_demand_units"] == 208
    assert data["per_record_total"] == 208
    assert data["sum_then_ceiling_total"] == 207


def test_forecast_per_record_ceiling_figures_are_served():
    """PRD §2.9: "A population record's `projected_annual_parts_units` is the
    family base demand multiplied by the serial's coverage multiplier and then
    by the weight class multiplier, with the product rounded up to the next
    whole unit."

    Design: Difficulty/combinatorial_formula/forecast_parts_demand_per_record_ceiling_vs_sum_then_ceiling
    """
    dealer = _dealer()
    lift = create_population_record(dealer, "SN-3001", product_family="LIFT_TRUCK",
                                    machine_operating_weight_lb=30000)
    exc = create_population_record(dealer, "SN-3002", product_family="EXCAVATION",
                                   machine_operating_weight_lb=50000)
    comp = create_population_record(dealer, "SN-3004", product_family="COMPACTION",
                                    machine_operating_weight_lb=50000)
    create_support_agreement(dealer, "SN-3001", plan_tier="PREMIUM")
    create_support_agreement(dealer, "SN-3002", plan_tier="PLUS")
    get_success_data(api_client.get_forecast(dealer["id"], parts_manager_headers()))

    assert get_success_data(api_client.get_population_record(
        lift["id"], parts_manager_headers()))["projected_annual_parts_units"] == 44
    assert get_success_data(api_client.get_population_record(
        exc["id"], parts_manager_headers()))["projected_annual_parts_units"] == 50
    assert get_success_data(api_client.get_population_record(
        comp["id"], parts_manager_headers()))["projected_annual_parts_units"] == 28


def test_coverage_multiplier_binds_the_plan_tier_constant():
    """PRD §2.9: "Coverage is `coverage_multiplier`: 1.5 when an `ACTIVE` support agreement with `plan_tier` `PREMIUM` covers the serial, 1.25 for `PLUS`, and 1.0 otherwise"
    PRD §2.9: "the multiplier is 0.8 for `LIGHT`, 1.0 for `MIDDLE` and 1.2 for
    `HEAVY`, recorded to two decimal places, half-up."

    Design: Corner/calculations/coverage_multiplier_selects_the_plan_tier_constant
    """
    dealer = _dealer()
    prem = create_population_record(dealer, "SN-3101", product_family="LIFT_TRUCK",
                                    machine_operating_weight_lb=50000)
    plus = create_population_record(dealer, "SN-3102", product_family="LIFT_TRUCK",
                                    machine_operating_weight_lb=50000)
    bare = create_population_record(dealer, "SN-3103", product_family="LIFT_TRUCK",
                                    machine_operating_weight_lb=50000)
    create_support_agreement(dealer, "SN-3101", plan_tier="PREMIUM")
    create_support_agreement(dealer, "SN-3102", plan_tier="PLUS")

    headers = parts_manager_headers()
    prem_data = get_success_data(api_client.get_population_record(prem["id"], headers))
    plus_data = get_success_data(api_client.get_population_record(plus["id"], headers))
    bare_data = get_success_data(api_client.get_population_record(bare["id"], headers))

    assert prem_data["coverage_multiplier"] == 1.5
    assert prem_data["projected_annual_parts_units"] == 54
    assert plus_data["coverage_multiplier"] == 1.25
    assert plus_data["projected_annual_parts_units"] == 45
    assert bare_data["coverage_multiplier"] == 1.0
    assert bare_data["projected_annual_parts_units"] == 36


def test_forecast_per_record_total_for_mixed_coverage():
    """PRD §2.9: "The canonical dealer forecast, served by `GET /dealer-network/machine-population-records/forecast` for a supplied `dealer_id`, is the `per_record_ceiling` variant: each `ACTIVE` record's product is rounded up to the next whole unit individually and the rounded values are then summed, with no further rounding."

    Design: Corner/calculations/coverage_multiplier_selects_the_plan_tier_constant
    """
    dealer = _dealer()
    create_population_record(dealer, "SN-3101", product_family="LIFT_TRUCK",
                             machine_operating_weight_lb=50000)
    create_population_record(dealer, "SN-3102", product_family="LIFT_TRUCK",
                             machine_operating_weight_lb=50000)
    create_population_record(dealer, "SN-3103", product_family="LIFT_TRUCK",
                             machine_operating_weight_lb=50000)
    create_support_agreement(dealer, "SN-3101", plan_tier="PREMIUM")
    create_support_agreement(dealer, "SN-3102", plan_tier="PLUS")

    data = get_forecast(dealer["id"])
    assert data["per_record_total"] == 135


def test_forecast_aggregation_does_not_round_twice():
    """PRD §2.9: "each `ACTIVE` record's product is rounded up to the next whole
    unit individually and the rounded values are then summed, with no further
    rounding."

    Design: Corner/calculations/forecast_floor_and_ceiling_are_honored_per_record
    """
    dealer = _dealer()
    a = create_population_record(dealer, "SN-3301", product_family="LIFT_TRUCK",
                                 machine_operating_weight_lb=50000)
    b = create_population_record(dealer, "SN-3302", product_family="LIFT_TRUCK",
                                 machine_operating_weight_lb=50000)
    data = get_forecast(dealer["id"])

    assert get_success_data(api_client.get_population_record(
        a["id"], parts_manager_headers()))["projected_annual_parts_units"] == 36
    assert get_success_data(api_client.get_population_record(
        b["id"], parts_manager_headers()))["projected_annual_parts_units"] == 36
    assert data["forecast_parts_demand_units"] == 72
    assert data["per_record_total"] == data["sum_then_ceiling_total"] == 72


def test_forecast_excludes_retired_records():
    """PRD §2.9: "`RETIRED` records contribute nothing to either variant."
    PRD §3.9: "Retiring a record moves `ACTIVE` to `RETIRED` and requires that the dealer carry a `TradeInUnit` with this machine serial in status `ACCEPTED`"

    Design: Corner/calculations/forecast_input_set_excludes_retired_population_records
    """
    dealer = _dealer()
    create_population_record(dealer, "SN-3201", product_family="LIFT_TRUCK",
                             machine_operating_weight_lb=50000)
    pop_b = create_population_record(dealer, "SN-3202", product_family="COMPACTION",
                                     machine_operating_weight_lb=50000)
    eo = create_equipment_order(dealer, machine_serial="SN-6201",
                                product_family="COMPACTION", trade_in_serial="SN-3202")
    submit_equipment_order(dealer, eo["id"])
    # PRD §3.9: retiring requires a TradeInUnit in status ACCEPTED, which the
    # financing approval is what puts the submitted order's trade-in into.
    approve_equipment_financing(eo["id"])

    before = get_forecast(dealer["id"])
    assert before["forecast_parts_demand_units"] == 64

    retire_population_record(pop_b["id"])
    after = get_forecast(dealer["id"])
    assert after["forecast_parts_demand_units"] == 36


def test_retired_record_remains_queryable():
    """PRD §3.9: "`RETIRED` records are excluded from every forecast and from
    the tier-weighted machine population."
    PRD §3.9: "Retiring a record moves `ACTIVE` to `RETIRED` and requires that the dealer carry a `TradeInUnit` with this machine serial in status `ACCEPTED`"

    Design: Corner/calculations/forecast_input_set_excludes_retired_population_records
    """
    dealer = _dealer()
    pop_b = create_population_record(dealer, "SN-3202", product_family="COMPACTION",
                                     machine_operating_weight_lb=50000)
    eo = create_equipment_order(dealer, machine_serial="SN-6201",
                                product_family="COMPACTION", trade_in_serial="SN-3202")
    submit_equipment_order(dealer, eo["id"])
    # PRD §3.9: retirement needs the dealer to carry an ACCEPTED trade-in row.
    approve_equipment_financing(eo["id"])
    retire_population_record(pop_b["id"])

    data = get_population_record(pop_b["id"])
    assert data["status"] == "RETIRED"


def test_support_agreement_enrollment_raises_coverage_immediately():
    """PRD §3.9: "Creating a support agreement recomputes the serial's
    `coverage_multiplier` on the machine population record and recomputes
    `required_stocking_units` on the dealer's commitments."
    PRD §3.9: "The agreement's `coverage_multiplier` is 1.0 for `BASIC`, 1.25 for `PLUS` and 1.5 for `PREMIUM`"

    Design: Corner/cross_cutting_complexity_layers/support_agreement_enrollment_recomputes_the_coverage_in_the_same_request
    """
    dealer = _dealer()
    pop = create_population_record(dealer, "SN-3401", product_family="EXCAVATION",
                                   machine_operating_weight_lb=50000)
    resp = api_client.create_support_agreement({
        "dealer_id": dealer["id"], "machine_serial": "SN-3401",
        "plan_tier": "PREMIUM", "enrolled_at": "2026-08-15T00:00:00Z",
    }, parts_manager_headers())
    support = get_success_data(resp, expected_status=201)

    assert support["coverage_multiplier"] == 1.5
    assert get_population_record(pop["id"])["coverage_multiplier"] == 1.5
    forecast = get_forecast(dealer["id"])
    assert forecast["forecast_parts_demand_units"] == 60
    assert forecast["forecast_parts_demand_units"] != 40


def test_weight_class_bands_are_inclusive_on_both_middle_edges():
    """PRD §2.9: "below 40000 pounds `LIGHT`, from 40000 pounds through 100000 pounds inclusive at both edges `MIDDLE`, and above 100000 pounds `HEAVY`"

    Design: Difficulty/boundary_precision_check/stocking_mandate_rate_band_boundary_at_exactly_twenty_four_hours
    """
    dealer = _dealer()
    low = create_population_record(dealer, "SN-4101", product_family="EXCAVATION",
                                   machine_operating_weight_lb=39999)
    mid = create_population_record(dealer, "SN-4102", product_family="EXCAVATION",
                                   machine_operating_weight_lb=40000)
    high = create_population_record(dealer, "SN-4103", product_family="EXCAVATION",
                                    machine_operating_weight_lb=100000)

    headers = parts_manager_headers()
    assert get_success_data(api_client.get_population_record(
        low["id"], headers))["weight_class_tier"] == "LIGHT"
    assert get_success_data(api_client.get_population_record(
        mid["id"], headers))["weight_class_tier"] == "MIDDLE"
    assert get_success_data(api_client.get_population_record(
        high["id"], headers))["weight_class_tier"] == "MIDDLE"