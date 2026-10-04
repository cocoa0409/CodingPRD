"""The stocking mandate: dual variants, nesting and boundary precision.

Every test here reads the mandate figures off a real commitment reached through
the declared API surface.
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    create_dealer,
    create_agreement,
    create_agreement_for_family,
    create_commitment,
    register_technicians,
    submit_agreement,
    submit_commitment,
    set_clock,
    dealer_version,
)


def _dealer_with_technicians(territory_code="T-410", legal_name="High Plains Machinery Co",
                             family="EXCAVATION"):
    set_clock()
    dealer = create_dealer(legal_name=legal_name, territory_code=territory_code)
    agreement = create_agreement(dealer, product_family=family)
    register_technicians(dealer, ("T-01", "T-02"), product_family=family)
    # PRD §3.4: submitting a commitment requires the owning agreement to be
    # SUBMITTED or ACTIVE, so the fixture must carry the agreement past DRAFT.
    submit_agreement(agreement["id"])
    return dealer, agreement


def test_stocking_mandate_serves_both_variants_on_identical_inputs():
    """PRD §2.7: "Two targets are then formed: one from the rate, being the
    tier-weighted numerator multiplied by the per-machine rate, and one from the
    dealer's plan, being `planned_annual_units` divided by 800. The active
    variant takes the larger of the ceiling of the rate target and the ceiling
    of the fill target, so it never rounds a term down. The final variant takes
    the larger of the floor of the rate target and the floor of the fill target,
    so it never rounds a term up, and `required_stocking_units_final` is
    therefore less than or equal to `required_stocking_units` on every input."
    PRD §2.7: "A `BASIC` window uses a rate of 0.101 units per machine; a `STANDARD` window uses 0.127; a `PREMIUM` window uses 0.152."

    Design: Difficulty/dual_variant_calc/stocking_mandate_active_ceiling_vs_final_floor_variant
    """
    dealer, agreement = _dealer_with_technicians()
    commitment = create_commitment(
        dealer, agreement,
        machine_population_units=500, machine_population_slope=1.0,
        planned_annual_units=50000, emergency_stocking_target_pct=50,
        emergency_fill_window_hours=24,
    )
    data = validate_success(api_client.submit_commitment(
        commitment["id"], {"X-User-ID": "pm-1", "X-User-Role": "PartsManager",
                           "Content-Type": "application/json"}))

    assert data["machine_population_tier"] == "MEDIUM"
    assert data["required_stocking_units"] == 64
    assert data["required_stocking_units_final"] == 63
    assert data["required_stocking_units_final"] <= data["required_stocking_units"]


def test_stocking_mandate_terms_are_not_interchanged():
    """PRD §2.7: "The active variant takes the larger of the ceiling of the rate
    target and the ceiling of the fill target, so it never rounds a term down.
    The final variant takes the larger of the floor of the rate target and the
    floor of the fill target, so it never rounds a term up, and
    `required_stocking_units_final` is therefore less than or equal to
    `required_stocking_units` on every input."

    Design: Difficulty/dual_variant_calc/stocking_mandate_active_ceiling_vs_final_floor_variant
    """
    dealer, agreement = _dealer_with_technicians(legal_name="Prairie Ironworks LLC")
    commitment = create_commitment(
        dealer, agreement,
        machine_population_units=500, machine_population_slope=1.0,
        planned_annual_units=50000, emergency_stocking_target_pct=50,
        emergency_fill_window_hours=24,
    )
    from test_helpers import parts_manager_headers
    data = validate_success(api_client.submit_commitment(
        commitment["id"], parts_manager_headers()))

    # The rate term is 500 * 0.127 = 63.5 and the fill term is 50000 / 800 = 62.5.
    assert data["required_stocking_units"] != 63
    assert data["required_stocking_units_final"] != 64


def test_stocking_mandate_nested_max_of_ceilings():
    """PRD §2.7: "The active variant takes the larger of the ceiling of the rate
    target and the ceiling of the fill target, so it never rounds a term down."
    PRD §2.7: "`availability_target_pct` is the emergency availability surrogate: it begins at 92.0 and adds one tenth of a percentage point for every percentage point by which `emergency_stocking_target_pct` exceeds 60, but never more than 4.0 percentage points in total, so the surrogate sits at 92.0 for a target of 60 or less and tops out at 96.0"

    Design: Difficulty/combinatorial_formula/stocking_mandate_nested_max_ceiling_composition
    """
    dealer, agreement = _dealer_with_technicians(territory_code="T-220",
                                                 legal_name="Prairie Ironworks LLC")
    commitment = create_commitment(dealer, agreement, machine_population_units=500,
                                   planned_annual_units=50000,
                                   emergency_fill_window_hours=24)
    from test_helpers import parts_manager_headers
    data = validate_success(api_client.submit_commitment(
        commitment["id"], parts_manager_headers()))

    assert data["machine_population_tier"] == "MEDIUM"
    assert data["required_stocking_units"] == 64
    assert data["availability_target_pct"] == 92.0


def test_stocking_mandate_single_term_composition_is_not_served():
    """PRD §2.7: "Two targets are then formed: one from the rate, being the
    tier-weighted numerator multiplied by the per-machine rate, and one from the
    dealer's plan, being `planned_annual_units` divided by 800. The active
    variant takes the larger of the ceiling of the rate target and the ceiling
    of the fill target, so it never rounds a term down."

    Design: Difficulty/combinatorial_formula/stocking_mandate_nested_max_ceiling_composition
    """
    dealer, agreement = _dealer_with_technicians(territory_code="T-220",
                                                 legal_name="Prairie Ironworks LLC")
    commitment = create_commitment(dealer, agreement, machine_population_units=500,
                                   planned_annual_units=50000,
                                   emergency_fill_window_hours=24)
    from test_helpers import parts_manager_headers
    data = validate_success(api_client.submit_commitment(
        commitment["id"], parts_manager_headers()))

    # ceil(63.5) == 64 and ceil(62.5) == 63, so max is 64 and neither single term is served.
    assert data["required_stocking_units"] != 63
    assert data["required_stocking_units"] == 64
    assert data["required_stocking_units_final"] == 63


def test_mandate_window_boundary_exactly_twenty_four_hours_keeps_standard_rate():
    """PRD §3.4: "A window of 8 hours or fewer is a `PREMIUM` emergency tier, a window of 24 hours or fewer is `STANDARD`, and a window above 24 hours is `BASIC`"
    PRD §2.7: "a `STANDARD` window uses 0.127; a `PREMIUM` window uses 0.152."

    Design: Difficulty/boundary_precision_check/stocking_mandate_rate_band_boundary_at_exactly_twenty_four_hours
    """
    from test_helpers import parts_manager_headers
    dealer, agreement = _dealer_with_technicians()

    commitment_24 = create_commitment(
        dealer, agreement, machine_population_units=80, machine_population_slope=1.0,
        planned_annual_units=1000, emergency_fill_window_hours=24,
    )
    data_24 = validate_success(api_client.submit_commitment(
        commitment_24["id"], parts_manager_headers()))
    assert data_24["required_stocking_units"] == 11

    commitment_245 = create_commitment(
        dealer, agreement, machine_population_units=80, machine_population_slope=1.0,
        planned_annual_units=1000, emergency_fill_window_hours=24.5,
    )
    data_245 = validate_success(api_client.submit_commitment(
        commitment_245["id"], parts_manager_headers()))
    assert data_245["required_stocking_units"] == 9


def test_mandate_window_boundary_weight_class_edge_is_inclusive():
    """PRD §2.9: "Weight class is `weight_class_tier_multiplier`, derived from `machine_operating_weight_lb`: below 40000 pounds `LIGHT`, from 40000 pounds through 100000 pounds inclusive at both edges `MIDDLE`, and above 100000 pounds `HEAVY`"
    PRD §2.9: "the multiplier is 0.8 for `LIGHT`, 1.0 for `MIDDLE` and 1.2 for `HEAVY`"

    Design: Difficulty/boundary_precision_check/stocking_mandate_rate_band_boundary_at_exactly_twenty_four_hours
    """
    from test_helpers import api_client as api, parts_manager_headers
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    resp = api.create_population_record({
        "dealer_id": dealer["id"], "product_family": "EXCAVATION",
        "machine_serial": "SN-4001", "machine_operating_weight_lb": 100001,
        "meter_hours": 500,
    }, parts_manager_headers())
    record = get_success_data(resp, expected_status=201)

    assert record["weight_class_tier"] == "HEAVY"
    assert record["projected_annual_parts_units"] == 48


def _money_headers():
    from test_helpers import parts_manager_headers
    return parts_manager_headers()


def test_tier_edge_numerator_exactly_100_is_small():
    """PRD §2.7: "a numerator below 100 is `MICRO`, 100 or more but below 500 is
    `SMALL`, 500 or more but below 1500 is `MEDIUM`, and 1500 or more is
    `LARGE`. The 100, 500 and 1500 edges belong to the higher tier — a numerator
    of exactly 100 is `SMALL`, exactly 1500 is `LARGE`, and exactly 99.99 is
    `MICRO`."

    Design: Corner/calculations/exact_tier_edge_weighted_numerator_100_is_small
    """
    dealer, agreement = _dealer_with_technicians()
    commitment = create_commitment(
        dealer, agreement, machine_population_units=500, machine_population_slope=0.2,
        planned_annual_units=5000, emergency_fill_window_hours=24,
    )
    data = validate_success(api_client.submit_commitment(
        commitment["id"], _money_headers()))
    assert data["machine_population_tier"] == "SMALL"


def test_tier_edge_numerator_just_below_100_is_micro():
    """PRD §2.7: "a numerator below 100 is `MICRO`, 100 or more but below 500 is `SMALL`, 500 or more but below 1500 is `MEDIUM`, and 1500 or more is `LARGE`. The 100, 500 and 1500 edges belong to the higher tier — a numerator of exactly 100 is `SMALL`, exactly 1500 is `LARGE`, and exactly 99.99 is `MICRO`."

    Design: Corner/calculations/exact_tier_edge_weighted_numerator_100_is_small
    """
    dealer, agreement = _dealer_with_technicians()
    commitment = create_commitment(
        dealer, agreement, machine_population_units=500,
        machine_population_slope=0.19998, planned_annual_units=5000,
        emergency_fill_window_hours=24,
    )
    data = validate_success(api_client.submit_commitment(
        commitment["id"], _money_headers()))
    assert data["machine_population_tier"] == "MICRO"


def test_commitment_starts_planned_with_mandate_already_derived():
    """PRD §3.4: "A stocking commitment is created by a `PartsManager` in
    `PLANNED` against an `agreement_id` and a denormalised `dealer_id`."
    PRD §2.5: "Creation of a new, stand-alone resource returns `201 Created`."

    Design: Corner/state_machines/parts_commitment_starts_in_planned_state
    """
    dealer, agreement = _dealer_with_technicians()
    data = validate_success(api_client.create_commitment({
        "agreement_id": agreement["id"],
        "dealer_id": dealer["id"],
        "product_family": "EXCAVATION",
        "machine_population_units": 500,
        "machine_population_slope": 1.0,
        "planned_annual_units": 50000,
        "emergency_stocking_target_pct": 50,
        "emergency_fill_window_hours": 24,
        "expected_dealer_version": dealer_version(dealer["id"]),
    }, _money_headers()), expected_status=201)

    assert data["status"] == "PLANNED"
    assert data["version"] == 1
    assert data["required_stocking_units"] == 64
    assert data["required_stocking_units_final"] == 63
    assert data["credit_balance_cents"] == 0


def test_availability_target_surrogate_reads_from_known_inputs():
    """PRD §2.7: "`availability_target_pct` is the emergency availability surrogate: it begins at 92.0 and adds one tenth of a percentage point for every percentage point by which `emergency_stocking_target_pct` exceeds 60, but never more than 4.0 percentage points in total, so the surrogate sits at 92.0 for a target of 60 or less and tops out at 96.0"

    Design: Corner/calculations/availability_target_known_inputs_surrogate_formula
    """
    dealer, agreement = _dealer_with_technicians()
    low = create_commitment(dealer, agreement, machine_population_units=500,
                            planned_annual_units=50000,
                            emergency_stocking_target_pct=50,
                            emergency_fill_window_hours=24)
    data_low = validate_success(api_client.submit_commitment(
        low["id"], _money_headers()))

    dealer2, agreement2 = _dealer_with_technicians(
        territory_code="T-411", legal_name="Coastal Lift Systems")
    high = create_commitment(dealer2, agreement2, machine_population_units=500,
                             planned_annual_units=50000,
                             emergency_stocking_target_pct=100,
                             emergency_fill_window_hours=24)
    data_high = validate_success(api_client.submit_commitment(
        high["id"], _money_headers()))

    assert data_low["availability_target_pct"] == 92.0
    assert data_high["availability_target_pct"] == 96.0
    assert data_high["availability_target_pct"] != 100.0


def test_availability_surrogate_cap_is_four_points_above_base():
    """PRD §2.7: "it begins at 92.0 and adds one tenth of a percentage point for every percentage point by which `emergency_stocking_target_pct` exceeds 60, but never more than 4.0 percentage points in total"

    Design: Corner/calculations/availability_target_known_inputs_surrogate_formula
    """
    dealer, agreement = _dealer_with_technicians()
    high = create_commitment(dealer, agreement, machine_population_units=500,
                             planned_annual_units=50000,
                             emergency_stocking_target_pct=100,
                             emergency_fill_window_hours=24)
    data_high = validate_success(api_client.submit_commitment(
        high["id"], _money_headers()))

    assert data_high["availability_target_pct"] - 92.0 == pytest.approx(4.0)
    assert data_high["availability_target_pct"] != 97.0